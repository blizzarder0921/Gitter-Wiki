# Gitter

本地 GitHub 开源项目管理工具，基于 Next.js 16 前端 + FastAPI 后端的双服务架构。

## 功能特性

- **项目管理**：通过 GitHub URL 自动抓取项目信息，支持 git clone/pull 一键同步
- **压缩包上传**：上传 .zip/.7z 压缩包自动解析项目信息，支持版本覆盖
- **知识图谱**：基于 graphify 构建项目代码知识图谱，可视化项目结构
- **能力报告**：为每个项目自动生成结构化的能力报告，输出到全局 Wiki 知识库
- **全局 Wiki 知识库**：统一的全局知识库，汇聚所有项目能力报告，支持 AI 对话、编辑器、图谱、健康检查、代码检查、深度研究、审查等功能
- **AI 翻译**：集成 15 个 LLM 提供商，支持流式翻译 README 等内容
- **分享文案**：AI 生成 5 种风格的分享文案（专业/轻松/幽默/文艺/极简）
- **版本归档**：自动管理版本压缩包，支持 .zip/.7z/.rar/.tar.gz 等格式
- **一键更新**：批量更新所有项目代码、README 和知识图谱
- **多克隆方式**：支持 HTTPS/SSH/gh_cli/镜像四种克隆方式
- **绿色版 Git**：支持自定义 git.exe 路径，适配便携版 Git
- **GitHub 资源抓取**：一键抓取 Issues/Releases/PRs/Commits 等资源
- **批量提取**：从文本中批量提取 GitHub 链接并解析项目信息
- **多语言**：支持中文、英文、日文、俄语、阿拉伯语 5 种语言界面

## 架构概览

Gitter 采用**知识生产与消费分离**架构：

- **知识生产侧**：每个项目通过 Graphify 构建知识图谱、通过能力报告生成器产出结构化 Markdown 报告
- **知识消费侧**：全局 LLM-Wiki 单例（`data/global-wiki/`）统一消费所有项目的能力报告，提供 AI 问答、搜索、图谱等知识服务

```
项目 A ──→ 能力报告 ──┐
项目 B ──→ 能力报告 ──┼──→ 全局 Wiki（data/global-wiki/）──→ AI 问答/搜索/图谱
项目 C ──→ 能力报告 ──┘
```

## 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Next.js | 16.1.2 | 前端框架（App Router） |
| FastAPI | 0.115.12 | 后端框架 |
| React | 19 | 前端 UI |
| Tailwind CSS | 4 | 样式 |
| shadcn/ui | - | UI 组件库 |
| Zustand | 5 | 状态管理 |
| SQLite | - | 数据库（Python sqlite3 + WAL） |
| i18next | 26 | 国际化 |
| motion | 12 | 动画 |
| graphify | 0.7.16 | 知识图谱（Python） |
| openai/anthropic/google-genai | - | 后端 LLM 调用 |

## 快速开始

### 环境要求

- Node.js >= 20.9.0
- pnpm >= 10.28.0
- Python 3.x（知识图谱和 Wiki 功能）
- 7-Zip（.7z 格式支持，可选）

### 一键启动

```powershell
# PowerShell
.\start.ps1

# 或 CMD
start.bat
```

启动脚本会自动检查环境、安装依赖、启动后端（8000 端口）和前端（3000 端口），并打开浏览器。

### 手动启动

```powershell
# 克隆项目
git clone https://github.com/blizzarder0921/Gitter-Wiki.git
cd Gitter-Wiki

# 安装前端依赖
cd frontend
pnpm install
cd ..

# 安装后端依赖
python -m venv backend\venv
backend\venv\Scripts\pip.exe install -r backend\requirements.txt

# 配置环境变量
copy frontend\.env.example frontend\.env.local
# 编辑 .env.local 填入 API Key

# 启动后端（端口 8000）
backend\venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir backend

# 启动前端（端口 3000，新终端）
cd frontend
npx next dev --webpack
```

浏览器访问 `http://localhost:3000`

前端通过 `next.config.ts` 中的 rewrites 配置将 `/api/*` 请求代理到后端 8000 端口。

### 生产构建

```powershell
cd frontend
pnpm build
pnpm start
```

## 配置说明

### LLM 提供商

在 `frontend\.env.local` 中配置 API Key：

```env
DEEPSEEK_API_KEY=sk-xxx
OPENAI_API_KEY=sk-xxx
QWEN_API_KEY=sk-xxx
```

可选配置 Base URL 和模型列表：

```env
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODELS=deepseek-v4-pro,deepseek-v4-flash
```

支持的提供商：OpenAI、Anthropic、Google、DeepSeek、Qwen、Kimi、MiniMax、GLM、SiliconFlow、Doubao、OpenRouter、Grok、Tencent、Xiaomi

也可在应用内设置面板中配置，存储在本地 SQLite 数据库中。

### 其他配置

```env
GITHUB_TOKEN=ghp_xxx          # GitHub API 认证（提高限额）
HTTP_PROXY=http://127.0.0.1:7890  # 代理配置
```

## 项目结构

```
gitter\
├── frontend\                  # Next.js 前端应用
│   ├── app\                    # App Router 页面
│   │   ├── wiki\                # 全局 Wiki 知识库页面
│   │   │   ├── layout.tsx       # Wiki 布局
│   │   │   └── page.tsx         # Wiki 入口页面
│   │   ├── layout.tsx           # 根布局
│   │   └── page.tsx             # 主页面
│   ├── components\             # React 组件
│   │   ├── settings\            # 设置面板组件
│   │   ├── share\               # 分享组件
│   │   ├── wiki\                # Wiki 功能组件
│   │   │   ├── chat\            # 聊天组件
│   │   │   ├── editor\          # 编辑器组件
│   │   │   ├── graph\           # 知识图谱组件
│   │   │   ├── health\          # 健康检查组件
│   │   │   ├── layout\          # 布局组件
│   │   │   ├── lint\            # 代码检查组件
│   │   │   ├── research\        # 研究组件
│   │   │   ├── review\          # 审查组件
│   │   │   └── search\          # 搜索组件
│   │   └── ui\                  # shadcn/ui 基础组件（20 个）
│   ├── lib\                     # 工具库
│   │   ├── ai\                  # AI 提供商配置
│   │   ├── hooks\               # React Hooks
│   │   ├── i18n\                # 国际化配置
│   │   ├── store\               # Zustand 状态存储
│   │   ├── types\               # TypeScript 类型
│   │   ├── utils\               # 工具函数
│   │   └── wiki\                # Wiki 类型定义
│   └── stores\                  # Zustand Store
│       ├── wiki-store.ts        # Wiki 状态管理
│       ├── chat-store.ts        # 聊天状态管理
│       ├── research-store.ts    # 研究状态管理
│       └── review-store.ts      # 审查状态管理
│
├── backend\                    # FastAPI 后端应用
│   ├── routers\                 # API 路由
│   │   ├── projects.py          # 项目管理
│   │   ├── settings.py          # 系统设置
│   │   ├── system.py            # 系统接口
│   │   ├── extract.py           # 压缩包解析
│   │   ├── github.py            # GitHub 信息
│   │   ├── translate.py         # AI 翻译
│   │   ├── graphify.py          # 知识图谱
│   │   ├── capabilities.py      # 能力报告 API
│   │   ├── wiki.py              # Wiki 核心 API（全局单例）
│   │   ├── wiki_chats.py        # Wiki 聊天 API
│   │   ├── wiki_global.py       # Wiki 全局统计 API
│   │   └── wiki_fs.py           # Wiki 文件系统 API
│   ├── services\                # 业务服务
│   │   ├── database.py          # 数据库服务
│   │   ├── project_service.py   # 项目服务
│   │   ├── capability_generator.py  # 能力报告生成器
│   │   ├── github_fetcher.py    # GitHub 资源抓取（可选数据源）
│   │   └── wiki\                # Wiki 服务
│   │       ├── ingest.py           # 自动摄入
│   │       ├── search.py           # 搜索服务
│   │       ├── lint.py             # 代码检查
│   │       ├── deep_research.py    # 深度研究
│   │       ├── llm_client.py       # LLM 客户端
│   │       ├── wiki_graph.py       # Wiki 图谱构建
│   │       └── ...                 # 其他 Wiki 服务
│   ├── models\                  # 数据模型
│   ├── config.py                # 配置文件
│   ├── main.py                  # 应用入口
│   └── requirements.txt         # Python 依赖
│
├── scripts\                    # 脚本文件
│   ├── backup.bat               # Git 备份脚本
│   └── dev.bat                  # 开发启动脚本
│
├── docs\                       # 项目文档
├── data\                      # 运行时数据
│   ├── gitter.db               # SQLite 数据库
│   ├── projects\               # 项目文件存储
│   ├── graphify\               # 知识图谱输出
│   └── global-wiki\            # 全局 Wiki 知识库
│       ├── sources\            # 能力报告等源文件
│       ├── wiki\               # 生成的 Wiki 页面
│       └── .llm-wiki\          # 元数据与设置
│
├── start.ps1                   # 一键启动脚本（PowerShell）
├── start.bat                   # 一键启动脚本（CMD）
└── README.md
```

## API 文档

后端 API 文档（Swagger UI）：`http://localhost:8000/api/docs`

## 注意事项

- 开发模式必须使用 `npx next dev --webpack`，Turbopack 与部分原生模块不兼容
- 本项目为 Windows 专属，路径使用 `\`，不支持 macOS/Linux
- 知识图谱和 Wiki 功能需要安装 Python 及 graphify 模块
- .7z 格式需要系统安装 7-Zip
- 前端通过 next.config.ts rewrites 代理 /api/* 到后端 8000 端口
- 后端使用 Python venv，启动命令为 `backend\venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload`
- Wiki 采用全局单例架构，所有项目的能力报告统一汇聚到 `data\global-wiki\`

## 许可证

MIT
