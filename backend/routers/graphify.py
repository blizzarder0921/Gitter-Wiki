"""
知识图谱路由模块

提供知识图谱构建、状态检查、结果获取等功能。

端点列表：
- POST /api/graphify/build       — 构建知识图谱
- GET  /api/graphify/check       — 检查 Python 和 graphify 可用性
- GET  /api/graphify/status/{id} — 获取图谱构建状态
- GET  /api/graphify/{id}/graph  — 获取图谱 HTML 内容
"""

import os
import sys
import json
import time
import asyncio
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from backend.services.project_service import get_project_by_id, update_project
from backend.config import PROJECTS_ROOT, GRAPHIFY_DIR, TEMP_DIR

# Windows 上 asyncio.create_subprocess_exec 不支持，使用线程池执行同步 subprocess
_executor = ThreadPoolExecutor(max_workers=2)

router = APIRouter(prefix="/api/graphify", tags=["graphify"])

# 图谱构建状态存储（内存中，进程重启后丢失）
_build_status: dict = {}


def _read_graph_stats(graph_dir: str) -> tuple:
    """读取图谱构建结果的统计信息

    从 graphify 输出目录中读取 graph.json 获取节点数和边数，
    并检查是否存在 HTML 文件。

    Args:
        graph_dir: graphify 输出目录路径
    Returns:
        (node_count, edge_count, has_html) 元组
    """
    node_count = 0
    edge_count = 0
    has_html = False

    if not graph_dir or not os.path.exists(graph_dir):
        return (node_count, edge_count, has_html)

    # 检查是否存在 HTML 文件
    for entry in os.listdir(graph_dir):
        if entry.endswith(".html"):
            has_html = True
            break

    # 从 graph.json 读取节点和边数量
    graph_json_path = os.path.join(graph_dir, "graph.json")
    if os.path.exists(graph_json_path):
        try:
            with open(graph_json_path, "r", encoding="utf-8") as f:
                graph_data = json.load(f)
            node_count = len(graph_data.get("nodes", []))
            # graphify 0.7 使用 "links" 作为边字段名（NetworkX json_graph 格式）
            edge_count = len(graph_data.get("edges", graph_data.get("links", [])))
        except (json.JSONDecodeError, OSError):
            pass

    return (node_count, edge_count, has_html)


def _verify_graphify_output(output_dir: str, max_wait: float = 10.0) -> bool:
    """验证 graphify 输出目录是否包含有效的知识图谱文件

    graphify 进程退出后，输出文件可能因磁盘 IO 缓冲还未完全落盘，
    或者 graphify 构建本身失败未生成完整输出。此函数等待并验证
    graph.json 文件存在且非空，确保知识图谱构建真正成功。

    Args:
        output_dir: graphify 输出目录路径
        max_wait: 最大等待秒数，默认 10 秒
    Returns:
        True 表示 graph.json 存在且非空；False 表示验证失败
    """
    graph_json_path = os.path.join(output_dir, "graph.json")
    deadline = time.time() + max_wait

    while time.time() < deadline:
        if os.path.exists(graph_json_path):
            try:
                size = os.path.getsize(graph_json_path)
                if size > 0:
                    with open(graph_json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict) and ("nodes" in data or "edges" in data):
                        return True
            except (json.JSONDecodeError, OSError):
                pass
        time.sleep(0.5)

    print(f"[Graphify Verify] 输出验证失败: {graph_json_path} 不存在或无效")
    return False


def _get_graphify_dir(project_id: int) -> str:
    """获取 graphify 数据目录路径

    Args:
        project_id: 项目 ID
    Returns:
        graphify 数据目录路径
    """
    return os.path.join(GRAPHIFY_DIR, str(project_id))


class BuildInput(BaseModel):
    """图谱构建请求体"""
    projectId: int
    options: Optional[dict] = None


@router.post("/build")
async def build_graph(body: BuildInput):
    """构建知识图谱

    调用 python -m graphify 构建项目知识图谱。

    返回格式：{"success": bool, "nodeCount": int, "edgeCount": int, "hasHtml": bool}
    前端 page.tsx 检查 data.success，访问 data.nodeCount、data.edgeCount、data.hasHtml。

    Args:
        body: 构建参数，包含 projectId 和可选 options
    Returns:
        构建结果，包含 success、nodeCount、edgeCount、hasHtml
    """
    try:
        project = get_project_by_id(body.projectId)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")

        # 图谱构建的输入必须是 clone 到的源代码目录
        # 不存在时应提示用户重新克隆项目，不能回退到 local_path（那是项目元数据目录）
        project_id_val = project["id"]
        source_dir = os.path.join(TEMP_DIR, str(project_id_val))
        if not os.path.exists(source_dir):
            raise HTTPException(
                status_code=400,
                detail="源代码目录不存在，请重新克隆或更新项目后再构建知识图谱",
            )

        # 初始化构建状态
        project_id = body.projectId
        _build_status[project_id] = {
            "status": "building",
            "progress": 0,
            "message": "正在构建知识图谱...",
        }

        # 构造输出目录（兼容自定义存储路径）
        _existing_path = project.get("local_path", "")
        _gf_projects_root = os.path.dirname(_existing_path) if _existing_path and os.path.isabs(_existing_path) else PROJECTS_ROOT
        output_dir = os.path.join(_gf_projects_root, project["name"], "graphify-out")

        # 使用 graphify 0.7 的 update 子命令
        cmd = [sys.executable, "-m", "backend.graphify", "update", source_dir, "--force"]

        # 异步执行构建命令（使用线程池在 Windows 上执行同步 subprocess）
        success = False
        node_count = 0
        edge_count = 0
        try:
            def _run_graphify():
                return subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=600,
                )

            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(_executor, _run_graphify),
                timeout=610,
            )

            if result.returncode == 0:
                # graphify 0.7 输出在 source_dir/graphify-out/ 下
                gf_output = os.path.join(source_dir, "graphify-out")
                if _verify_graphify_output(gf_output):
                    # 迁移输出到目标目录
                    if os.path.exists(output_dir):
                        shutil.rmtree(output_dir, ignore_errors=True)
                    try:
                        shutil.move(gf_output, output_dir)
                    except Exception:
                        shutil.copytree(gf_output, output_dir)

                    success = True
                    # 读取节点和边数
                    graph_json_path = os.path.join(output_dir, "graph.json")
                    try:
                        with open(graph_json_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        node_count = len(data.get("nodes", []))
                        edge_count = len(data.get("edges", []))
                    except Exception:
                        pass
                    _build_status[project_id] = {
                        "status": "completed",
                        "progress": 100,
                        "message": "知识图谱构建完成",
                        "outputDir": output_dir,
                    }
                    update_project(project_id, {"graph_path": output_dir})

                    # 构建成功后，尝试使用 LLM 生成社区语义标签
                    try:
                        from backend.services.community_labeler import generate_community_labels
                        labels_ok = generate_community_labels(output_dir)
                        if labels_ok:
                            print(f"[Graphify Build] 项目 {project_id} LLM 社区标签生成完成")
                        else:
                            print(f"[Graphify Build] 项目 {project_id} LLM 社区标签生成未成功（使用自动标签兜底）")
                    except Exception as lbl_err:
                        print(f"[Graphify Build] 项目 {project_id} LLM 标签生成失败（非致命）: {lbl_err}")
                else:
                    _build_status[project_id] = {
                        "status": "failed",
                        "progress": 0,
                        "message": "构建进程退出但输出验证失败，graph.json 不存在或无效",
                    }
            else:
                err_msg = result.stderr or "未知错误"
                _build_status[project_id] = {
                    "status": "failed",
                    "progress": 0,
                    "message": f"构建失败：{err_msg}",
                }

        except asyncio.TimeoutError:
            _build_status[project_id] = {
                "status": "failed",
                "progress": 0,
                "message": "构建超时（10 分钟）",
            }
        except FileNotFoundError:
            _build_status[project_id] = {
                "status": "failed",
                "progress": 0,
                "message": "graphify 模块未安装，请检查 backend/graphify/ 目录是否完整",
            }

        # 读取构建结果统计信息（成功时已在上面读取 node_count/edge_count，这里补充 has_html）
        _, _, has_html = _read_graph_stats(output_dir)

        return {
            "success": success,
            "nodeCount": node_count,
            "edgeCount": edge_count,
            "hasHtml": has_html,
        }

    except HTTPException:
        raise
    except Exception as err:
        _build_status[body.projectId] = {
            "status": "failed",
            "progress": 0,
            "message": str(err),
        }
        raise HTTPException(status_code=500, detail=f"构建失败：{str(err)}")


@router.get("/check")
async def check_graphify():
    """检查 Python 和 graphify 可用性

    Returns:
        Python 和 graphify 的安装状态及版本信息
    """
    result = {"python": False, "graphify": False, "pythonVersion": None, "graphifyVersion": None}

    # 检查 Python（使用线程池在 Windows 上执行同步 subprocess）
    try:
        def _check_python():
            return subprocess.run(
                ["python", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )

        loop = asyncio.get_event_loop()
        py_result = await asyncio.wait_for(
            loop.run_in_executor(_executor, _check_python),
            timeout=15,
        )
        if py_result.returncode == 0:
            result["python"] = True
            version_output = (py_result.stdout or py_result.stderr or "").strip()
            result["pythonVersion"] = version_output.replace("Python ", "")
    except Exception:
        pass

    # 检查 graphify
    try:
        def _check_graphify():
            return subprocess.run(
                [sys.executable, "-m", "backend.graphify", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )

        loop = asyncio.get_event_loop()
        gf_result = await asyncio.wait_for(
            loop.run_in_executor(_executor, _check_graphify),
            timeout=15,
        )
        if gf_result.returncode == 0:
            result["graphify"] = True
            version_output = (gf_result.stdout or gf_result.stderr or "").strip()
            result["graphifyVersion"] = version_output
    except Exception:
        pass

    return result


@router.get("/status/{project_id}")
async def get_build_status(project_id: int):
    """获取图谱构建状态

    返回格式：{"exists": bool, "hasHtml": bool, "nodeCount": int, "edgeCount": int}
    前端 page.tsx 期望此格式，通过检查 data/graphify/{id}/ 目录判断 exists 和 hasHtml。

    Args:
        project_id: 项目 ID
    Returns:
        图谱存在状态和统计信息
    """
    # 优先从项目名称推导 graphify-out 目录（data/projects/{name}/graphify-out/）
    project = get_project_by_id(project_id)
    graphify_dir = ""
    exists = False

    if project and project.get("name"):
        _existing_path = project.get("local_path", "")
        _gf_projects_root = os.path.dirname(_existing_path) if _existing_path and os.path.isabs(_existing_path) else PROJECTS_ROOT
        project_graphify_dir = os.path.join(_gf_projects_root, project["name"], "graphify-out")
        if os.path.exists(project_graphify_dir) and os.path.isdir(project_graphify_dir):
            graphify_dir = project_graphify_dir
            exists = True

    # 回退：检查旧路径 data/graphify/{project_id}/
    if not exists:
        legacy_dir = _get_graphify_dir(project_id)
        if os.path.exists(legacy_dir) and os.path.isdir(legacy_dir):
            graphify_dir = legacy_dir
            exists = True

    if not exists:
        return {"exists": False, "hasHtml": False, "nodeCount": 0, "edgeCount": 0}

    # 读取图谱统计信息
    node_count, edge_count, has_html = _read_graph_stats(graphify_dir)

    return {
        "exists": exists,
        "hasHtml": has_html,
        "nodeCount": node_count,
        "edgeCount": edge_count,
    }


@router.get("/{project_id}/graph")
async def get_graph(project_id: int):
    """获取图谱 HTML 内容

    直接返回 HTML 内容（Content-Type: text/html），前端用 <iframe src=...> 直接加载。

    Args:
        project_id: 项目 ID
    Returns:
        HTML Response
    """
    try:
        project = get_project_by_id(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")

        # 查找图谱文件目录：优先项目 graphify-out 目录，其次旧路径
        _existing_path = project.get("local_path", "")
        _gf_projects_root = os.path.dirname(_existing_path) if _existing_path and os.path.isabs(_existing_path) else PROJECTS_ROOT
        graph_dir = os.path.join(_gf_projects_root, project["name"], "graphify-out")
        if not os.path.exists(graph_dir):
            graph_dir = _get_graphify_dir(project_id)

        if not os.path.exists(graph_dir):
            raise HTTPException(status_code=404, detail="图谱未构建")

        # 查找 HTML 文件
        html_file = None
        for name in ["index.html", "graph.html", "knowledge-graph.html"]:
            path = os.path.join(graph_dir, name)
            if os.path.exists(path):
                html_file = path
                break

        if not html_file:
            # 查找目录下任意 .html 文件
            for entry in os.listdir(graph_dir):
                if entry.endswith(".html"):
                    html_file = os.path.join(graph_dir, entry)
                    break

        if not html_file:
            raise HTTPException(status_code=404, detail="图谱 HTML 文件不存在")

        with open(html_file, "r", encoding="utf-8") as f:
            html_content = f.read()

        # 直接返回 HTML 内容，前端 <iframe src=...> 直接加载
        return Response(content=html_content, media_type="text/html")

    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"获取图谱失败：{str(err)}")
