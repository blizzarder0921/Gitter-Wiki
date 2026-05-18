/**
 * Wiki 全局状态管理 (Zustand Store)
 *
 * 管理 Wiki 文件树、选中文件、视图切换等全局状态。
 * 适配全局 Wiki 架构，所有 API 调用不再需要 projectId 参数。
 *
 * 核心职责：
 * - 文件树管理（fileTree / selectedFile / fileContent）
 * - 视图切换（activeView / chatExpanded）
 * - 知识库刷新（refreshKnowledge → POST /api/wiki/ingest）
 *
 * 注意：
 * - LLM 配置已统一至 settings-store，本 store 不再维护 llmConfig
 * - 搜索 & 嵌入配置已统一至 settings-store
 */

import { create } from 'zustand'
import type { IngestProgress, HealthScore } from '@/lib/wiki/types'
import { useSettingsStore } from '@/lib/store/settings'

// ---------------------------------------------------------------------------
// 类型定义（内联，避免跨模块循环依赖）
// ---------------------------------------------------------------------------

/** 文件树节点 */
export interface FileNode {
  /** 文件/文件夹名称 */
  name: string
  /** 绝对路径 */
  path: string
  /** 是否为目录 */
  is_dir: boolean
  /** 子节点（仅目录） */
  children?: FileNode[]
}

/** Wiki 视图类型 */
export type WikiView =
  | 'chat'
  | 'sources'
  | 'graph'
  | 'lint'
  | 'review'
  | 'research'
  | 'health'
  | 'settings'

// ---------------------------------------------------------------------------
// Store 状态与操作接口
// ---------------------------------------------------------------------------

interface WikiState {
  /** 项目文件树 */
  fileTree: FileNode[]
  /** 当前选中的文件路径 */
  selectedFile: string | null
  /** 当前文件内容 */
  fileContent: string
  /** 待滚动到的图片 src（一次性消费） */
  pendingScrollImageSrc: string | null
  /** 聊天面板是否展开 */
  chatExpanded: boolean
  /** 当前活跃视图 */
  activeView: WikiView
  /** 数据版本号（用于触发图谱重建等） */
  dataVersion: number
  /** 是否正在摄入 */
  isIngesting: boolean
  /** 摄入进度 */
  ingestProgress: IngestProgress | null
  /** 健康度评分 */
  healthScore: HealthScore | null
  /** 加载状态 */
  loading: boolean

  // ── 状态操作 ──

  setFileTree: (tree: FileNode[]) => void
  setSelectedFile: (path: string | null) => void
  setFileContent: (content: string) => void
  setPendingScrollImageSrc: (src: string | null) => void
  setChatExpanded: (expanded: boolean) => void
  setActiveView: (view: WikiView) => void

  // ── 数据版本 ──

  bumpDataVersion: () => void

  // ── 摄入 & 健康度 ──

  setIsIngesting: (ingesting: boolean) => void
  setIngestProgress: (progress: IngestProgress | null) => void
  setHealthScore: (score: HealthScore | null) => void
  setLoading: (loading: boolean) => void

  // ── 异步加载 ──

  /** 加载文件树 */
  loadFileTree: () => Promise<void>
  /** 加载 Wiki 状态（摄入进度、健康度等） */
  loadStatus: () => Promise<void>

  // ── 知识库刷新 ──

  /** 刷新知识库（调用 POST /api/wiki/ingest） */
  refreshKnowledge: () => Promise<void>
}

// ---------------------------------------------------------------------------
// Store 创建
// ---------------------------------------------------------------------------

/** Wiki 全局状态管理 store */
export const useWikiStore = create<WikiState>((set, get) => ({
  fileTree: [],
  selectedFile: null,
  fileContent: '',
  pendingScrollImageSrc: null,
  chatExpanded: false,
  activeView: 'chat',

  dataVersion: 0,

  isIngesting: false,
  ingestProgress: null,
  healthScore: null,
  loading: false,

  // ── 状态操作实现 ──

  setFileTree: (fileTree) => set({ fileTree }),
  setSelectedFile: (selectedFile) => set({ selectedFile }),
  setFileContent: (fileContent) => set({ fileContent }),
  setPendingScrollImageSrc: (pendingScrollImageSrc) =>
    set({ pendingScrollImageSrc }),
  setChatExpanded: (chatExpanded) => set({ chatExpanded }),
  setActiveView: (activeView) => set({ activeView }),

  // ── 数据版本 ──

  /** 递增 dataVersion，用于触发依赖数据的组件（如图谱）重新计算 */
  bumpDataVersion: () =>
    set((state) => ({ dataVersion: state.dataVersion + 1 })),

  // ── 摄入 & 健康度 setter 实现 ──

  /** 设置摄入中状态 */
  setIsIngesting: (isIngesting) => set({ isIngesting }),
  /** 设置摄入进度 */
  setIngestProgress: (ingestProgress) => set({ ingestProgress }),
  /** 设置健康度评分 */
  setHealthScore: (healthScore) => set({ healthScore }),
  /** 设置加载状态 */
  setLoading: (loading) => set({ loading }),

  // ── 异步加载实现 ──

  /**
   * 加载文件树
   *
   * 通过全局 API 获取 Wiki 目录的文件树结构，
   * 写入 fileTree 状态并递增 dataVersion 触发相关组件刷新。
   */
  loadFileTree: async () => {
    set({ loading: true })
    try {
      const res = await fetch('/api/wiki/filetree')
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`)
      }
      const tree: FileNode[] = await res.json()
      set({ fileTree: Array.isArray(tree) ? tree : [] })
    } catch {
      // 加载失败时保持空数组，避免阻塞整体渲染
    } finally {
      set({ loading: false })
    }
  },

  /**
   * 加载 Wiki 状态
   *
   * 通过全局状态 API 获取健康度评分、摄入进度等数据，
   * 并行写入 healthScore、ingestProgress 等状态字段。
   */
  loadStatus: async () => {
    try {
      const res = await fetch('/api/wiki/status')
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`)
      }
      const data = await res.json()
      if (!data || data.error) return

      // 设置健康度评分
      if (data.healthSnapshot) {
        set({
          healthScore: {
            score: data.healthSnapshot.score ?? 0,
            nodeCount: data.healthSnapshot.nodeCount ?? 0,
            edgeCount: data.healthSnapshot.edgeCount ?? 0,
            isolatedPages: data.healthSnapshot.isolatedPages ?? 0,
            brokenLinks: data.healthSnapshot.brokenLinks ?? 0,
            outdatedConcepts: data.healthSnapshot.outdatedConcepts ?? 0,
          },
        })
      }

      // 设置摄入进度
      if (data.lastIngestedAt) {
        set({
          isIngesting: false,
          ingestProgress: {
            status: 'completed',
            currentFile: null,
            totalFiles: data.nodeCount ?? 0,
            processedFiles: data.nodeCount ?? 0,
            currentPage: 0,
            errorMessage: null,
          },
        })
      }
    } catch {
      // 加载失败时静默处理，已有默认空值兜底
    }
  },

  /**
   * 刷新知识库
   *
   * 调用 POST /api/wiki/ingest 接口触发知识库摄入，
   * 完成后刷新文件树和状态。
   */
  refreshKnowledge: async () => {
    set({ isIngesting: true })
    try {
      // 从系统设置获取 LLM 配置（与设置页面一致）
      const { providerId, modelId, providersConfig } = useSettingsStore.getState()
      const currentProvider = providersConfig[providerId]
      const apiKey = currentProvider?.apiKey || ''
      const baseUrl = currentProvider?.baseUrl || currentProvider?.defaultBaseUrl || ''

      const res = await fetch('/api/wiki/ingest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          providerId,
          modelId,
          apiKey,
          baseUrl,
        }),
      })
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.detail || `摄入失败：HTTP ${res.status}`)
      }
      // 摄入完成后刷新文件树和状态
      await get().loadFileTree()
      await get().loadStatus()
    } catch {
      // 摄入失败时静默处理
    } finally {
      set({ isIngesting: false })
    }
  },
}))
