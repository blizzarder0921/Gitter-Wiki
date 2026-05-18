'use client';

import { useState } from 'react';
import { type Project } from '@/lib/types';
import { createLogger } from '@/lib/logger';
import { toast } from 'sonner';

/**
 * useGraph - 知识图谱查看与构建管理 Hook
 *
 * 封装图谱状态检查、弹窗控制、手动构建等逻辑，
 * 供 HomePage 组件统一调用，减少页面组件的状态和函数定义。
 *
 * handleOpenGraph 与 handleBuildGraph 接收 project 参数，
 * 而非依赖闭包变量，确保调用方可以明确传参。
 */
export function useGraph() {
  const log = createLogger('Graph');

  /** 图谱状态信息：是否存在、HTML 文件、节点/边数量 */
  const [graphifyStatus, setGraphifyStatus] = useState<{
    exists: boolean;
    hasHtml: boolean;
    nodeCount: number;
    edgeCount: number;
  } | null>(null);

  /** 图谱弹窗显隐 */
  const [showGraphDialog, setShowGraphDialog] = useState(false);

  /** 图谱构建中标志 */
  const [buildingGraph, setBuildingGraph] = useState(false);

  /**
   * 检查指定项目的知识图谱状态
   * @param projectId 目标项目 ID
   * @returns 图谱状态数据，失败返回 null
   */
  const checkGraphifyStatus = async (projectId: number) => {
    try {
      const res = await fetch(`/api/graphify/status/${projectId}`);
      if (res.ok) {
        const data = await res.json();
        setGraphifyStatus(data);
        return data;
      }
    } catch {}
    return null;
  };

  /**
   * 打开知识图谱查看弹窗
   * 先检查图谱状态再展示弹窗，图谱已构建则加载 HTML，未构建则显示空状态
   * @param project 目标项目
   */
  const handleOpenGraph = async (project: Project) => {
    const status = await checkGraphifyStatus(project.id);
    setShowGraphDialog(true);
  };

  /**
   * 手动构建知识图谱
   * 调用后端 build API，构建完成后自动刷新状态并加载图谱
   * @param project 目标项目
   */
  const handleBuildGraph = async (project: Project) => {
    if (buildingGraph) return;
    setBuildingGraph(true);
    try {
      const res = await fetch('/api/graphify/build', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ projectId: project.id }),
      });
      const data = await res.json();
      if (res.ok && data.success) {
        toast.success(`知识图谱构建完成：${data.nodeCount} 节点，${data.edgeCount} 边`);
        await checkGraphifyStatus(project.id);
      } else {
        toast.error(data.detail || '知识图谱构建失败');
      }
    } catch (err) {
      log.error('Failed to build graph:', err);
      toast.error('知识图谱构建失败');
    } finally {
      setBuildingGraph(false);
    }
  };

  return {
    graphifyStatus,
    showGraphDialog,
    setShowGraphDialog,
    buildingGraph,
    checkGraphifyStatus,
    handleOpenGraph,
    handleBuildGraph,
  };
}
