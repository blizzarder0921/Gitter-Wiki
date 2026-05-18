'use client';

/**
 * 研究 Research Store -- 管理 Wiki 深度研究任务
 *
 * 基础骨架实现，核心研究流程（搜索、综合、保存）通过
 * API 调用 `/api/wiki/research` 完成。
 * Store 负责维护任务队列的状态与进度展示。
 */
import { create } from 'zustand';
import type { ResearchTask, ResearchTaskStatus } from '@/lib/wiki/types';

// ---------------------------------------------------------------------------
// State 类型定义
// ---------------------------------------------------------------------------

/** 研究存储的完整状态与操作方法 */
interface ResearchState {
  /** 所有研究任务列表 */
  tasks: ResearchTask[];
  /** 研究面板是否展开 */
  panelOpen: boolean;
  /** 最大并发研究任务数 */
  maxConcurrent: number;

  /**
   * 添加研究任务到队列
   * @param topic - 研究主题
   * @returns 新任务 ID
   */
  addTask: (topic: string) => string;

  /**
   * 更新指定任务的字段
   * @param id - 任务 ID
   * @param updates - 需更新的字段
   */
  updateTask: (id: string, updates: Partial<ResearchTask>) => void;

  /** 移除指定任务 */
  removeTask: (id: string) => void;
  /** 批量设置任务列表（从 API 加载后调用） */
  setTasks: (tasks: ResearchTask[]) => void;
  /** 设置面板展开/收起 */
  setPanelOpen: (open: boolean) => void;
  /** 获取当前运行中的任务数量 */
  getRunningCount: () => number;
  /** 获取下一个排队中的任务 */
  getNextQueued: () => ResearchTask | undefined;
}

// ---------------------------------------------------------------------------
// 工具函数
// ---------------------------------------------------------------------------

/** 全局任务计数器 */
let counter = 0;

// ---------------------------------------------------------------------------
// Store 实现
// ---------------------------------------------------------------------------

/**
 * 研究 Store
 *
 * 管理深度研究任务的完整生命周期：排队、运行、完成。
 * 实际研究流程由服务端 `/api/wiki/research` 处理，
 * 前端通过 updateTask 轮询或 SSE 更新任务进度。
 */
export const useResearchStore = create<ResearchState>((set, get) => ({
  // ---- 初始状态 ----
  tasks: [],
  panelOpen: false,
  maxConcurrent: 3,

  // ---- 任务管理 ----

  /** 添加新研究任务，状态初始为 queued，自动打开面板 */
  addTask: (topic) => {
    const id = `research-${++counter}`;
    set((state) => ({
      tasks: [
        ...state.tasks,
        {
          id,
          topic,
          status: 'queued' as ResearchTaskStatus,
          progress: 0,
          createdAt: Date.now(),
          updatedAt: Date.now(),
        },
      ],
      panelOpen: true,
    }));
    return id;
  },

  /** 更新任务属性（状态、进度等），同时刷新 updatedAt */
  updateTask: (id, updates) =>
    set((state) => ({
      tasks: state.tasks.map((t) =>
        t.id === id ? { ...t, ...updates, updatedAt: Date.now() } : t,
      ),
    })),

  /** 从队列中移除任务 */
  removeTask: (id) =>
    set((state) => ({
      tasks: state.tasks.filter((t) => t.id !== id),
    })),

  /** 全量覆盖任务列表（从 API 加载后调用） */
  setTasks: (tasks) => set({ tasks }),

  setPanelOpen: (panelOpen) => set({ panelOpen }),

  // ---- 查询方法 ----

  /** 统计当前活跃（进行中）的任务数 */
  getRunningCount: () => {
    const { tasks } = get();
    return tasks.filter(
      (t) =>
        t.status === 'searching' ||
        t.status === 'synthesizing' ||
        t.status === 'saving',
    ).length;
  },

  /** 获取第一个状态为 queued 的任务 */
  getNextQueued: () => {
    const { tasks } = get();
    return tasks.find((t) => t.status === 'queued');
  },
}));
