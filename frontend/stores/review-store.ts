'use client';

/**
 * 审核 Review Store -- 管理 Wiki 审核项列表
 *
 * 基础骨架实现，核心审核流程（扫描、分类、解决）由服务端
 * `/api/wiki/review` API 处理。
 * Store 负责维护审核项的展示状态与批量操作。
 */
import { create } from 'zustand';
import type { ReviewItem } from '@/lib/wiki/types';

// ---------------------------------------------------------------------------
// State 类型定义
// ---------------------------------------------------------------------------

/** 审核存储的完整状态与操作方法 */
interface ReviewState {
  /** 当前所有审核项 */
  items: ReviewItem[];

  /**
   * 单条添加审核项
   * @param item - 不含 id、resolved、createdAt 的审核项
   */
  addItem: (item: Omit<ReviewItem, 'id' | 'resolved' | 'createdAt'>) => void;

  /** 批量覆盖审核项列表 */
  setItems: (items: ReviewItem[]) => void;

  /**
   * 将审核项标记为已解决
   * @param id - 审核项 ID
   * @param action - 执行的解决操作
   */
  resolveItem: (id: string, action: string) => void;

  /** 移除指定审核项 */
  dismissItem: (id: string) => void;

  /** 清除所有已解决的审核项 */
  clearResolved: () => void;
}

// ---------------------------------------------------------------------------
// 工具函数
// ---------------------------------------------------------------------------

/** 全局审核项计数器 */
let counter = 0;

// ---------------------------------------------------------------------------
// Store 实现
// ---------------------------------------------------------------------------

/**
 * 审核 Store
 *
 * 管理 Wiki 审核项的展示与操作。审核项由后端 Lint 扫描生成，
 * 前端通过此 Store 维护列表、标记解决、批量清理。
 */
export const useReviewStore = create<ReviewState>((set) => ({
  // ---- 初始状态 ----
  items: [],

  // ---- 审核项 CRUD ----

  /** 添加单条审核项，自动补全 id、resolved、createdAt */
  addItem: (item) =>
    set((state) => ({
      items: [
        ...state.items,
        {
          ...item,
          id: `review-${++counter}`,
          resolved: false,
          createdAt: new Date().toISOString(),
        },
      ],
    })),

  /** 全量覆盖审核项列表（通常从 API 加载后调用） */
  setItems: (items) => set({ items }),

  /** 标记审核项为已解决，记录解决操作 */
  resolveItem: (id, action) =>
    set((state) => ({
      items: state.items.map((item) =>
        item.id === id ? { ...item, resolved: true } : item,
      ),
    })),

  /** 从列表中移除指定审核项 */
  dismissItem: (id) =>
    set((state) => ({
      items: state.items.filter((item) => item.id !== id),
    })),

  /** 批量清除所有已解决的审核项 */
  clearResolved: () =>
    set((state) => ({
      items: state.items.filter((item) => !item.resolved),
    })),
}));
