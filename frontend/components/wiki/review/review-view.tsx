'use client';

/**
 * Wiki 审核队列视图组件 -- review-view.tsx
 *
 * 从 /api/wiki/review 加载待审核项列表，展示每条审核项的类型、
 * 描述和建议操作，并支持批准、跳过、删除三种操作。
 *
 * 数据来源：GET /api/wiki/review?status=pending
 * 审核操作：POST /api/wiki/review/{reviewId}
 *
 * 依赖：
 *   - @/lib/wiki/types：ReviewItem / ReviewItemType 类型定义
 *   - lucide-react：Check / X / Trash2 / Loader2 / ClipboardCheck 图标
 */

import { useEffect, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Check, X, Trash2, Loader2, ClipboardCheck } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useReviewStore } from '@/stores/review-store';
import type { ReviewItem, ReviewItemType } from '@/lib/wiki/types';

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------

/** 组件 Props */
interface ReviewViewProps {
  /** 自定义类名 */
  className?: string;
}

/** 审核操作类型 */
type ReviewAction = 'approve' | 'skip' | 'delete';

// ---------------------------------------------------------------------------
// 常量定义
// ---------------------------------------------------------------------------

/**
 * 审核项类型的中文标签与样式映射
 * 根据类型返回对应的展示文案和 Tailwind 配色
 */
const TYPE_CONFIG: Record<ReviewItemType, { label: string; badgeClass: string }> = {
  contradiction: {
    label: '矛盾',
    badgeClass: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  },
  duplicate: {
    label: '重复',
    badgeClass: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  },
  'missing-page': {
    label: '缺失页面',
    badgeClass: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  },
  confirm: {
    label: '待确认',
    badgeClass: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
  },
  suggestion: {
    label: '建议',
    badgeClass: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  },
};

// ---------------------------------------------------------------------------
// 主组件
// ---------------------------------------------------------------------------

/**
 * Wiki 审核队列视图
 *
 * 加载待处理的审核项，展示每条审核项的类型标签、问题描述和建议操作。
 * 用户可对每条审核项执行批准（approve）、跳过（skip）或删除（delete）操作。
 * 操作通过 POST 请求发送至服务端，完成后从列表中移除该项。
 */
export function ReviewView({ className }: ReviewViewProps) {
  /** 审核项列表 */
  const [items, setItems] = useState<ReviewItem[]>([]);
  /** 加载状态 */
  const [loading, setLoading] = useState(true);
  /** 错误信息 */
  const [error, setError] = useState<string | null>(null);
  /** 正在处理中的审核项 ID（用于按钮 loading 态） */
  const [processingId, setProcessingId] = useState<string | null>(null);

  /**
   * 从服务端加载待审核项列表
   * 仅获取 status=pending（未解决）的审核项
   */
  const fetchItems = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/wiki/review?status=pending');
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || '获取审核队列失败');
      }
      const data: ReviewItem[] = await res.json();
      setItems(data);
      // 同步到全局 ReviewStore，使父页面的审核角标正确显示
      useReviewStore.getState().setItems(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : '未知错误';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  /* eslint-disable react-hooks/set-state-in-effect -- 组件挂载时加载数据 */
  useEffect(() => {
    fetchItems();
  }, [fetchItems]);
  /* eslint-enable react-hooks/set-state-in-effect */

  /**
   * 执行审核操作（批准/跳过/删除）
   *
   * 向 POST /api/wiki/review/{reviewId} 发送请求，
   * 请求体包含 action 字段，服务端根据 action 决定处理方式。
   *
   * @param reviewId - 审核项 ID
   * @param action - 操作类型：approve 批准、skip 跳过、delete 删除
   */
  const handleAction = useCallback(
    async (reviewId: string, action: ReviewAction) => {
      setProcessingId(reviewId);
      try {
        const res = await fetch(`/api/wiki/review/${reviewId}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action }),
        });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.detail || `操作失败：${action}`);
        }
        /** 操作成功，从列表中移除该审核项 */
        setItems((prev) => prev.filter((item) => item.id !== reviewId));
      } catch (err) {
        const message = err instanceof Error ? err.message : '操作失败';
        setError(message);
      } finally {
        setProcessingId(null);
      }
    },
    [],
  );

  // -------------------------------------------------------------------------
  // 渲染：加载中状态
  // -------------------------------------------------------------------------

  if (loading) {
    return (
      <div className={cn('flex items-center justify-center py-16', className)}>
        <Loader2 className="w-6 h-6 animate-spin text-primary" />
      </div>
    );
  }

  // -------------------------------------------------------------------------
  // 渲染：错误状态
  // -------------------------------------------------------------------------

  if (error) {
    return (
      <div className={cn('flex flex-col items-center justify-center py-16 gap-3', className)}>
        <p className="text-sm text-destructive">{error}</p>
        <button
          onClick={fetchItems}
          className="text-xs text-primary hover:underline transition-colors"
        >
          点击重试
        </button>
      </div>
    );
  }

  // -------------------------------------------------------------------------
  // 渲染：空状态
  // -------------------------------------------------------------------------

  if (items.length === 0) {
    return (
      <div className={cn('flex flex-col items-center justify-center py-16 gap-3 text-muted-foreground', className)}>
        <ClipboardCheck className="w-12 h-12 opacity-30" />
        <p className="text-sm">暂无待审核项目</p>
        <p className="text-xs">所有审核项已处理完毕</p>
      </div>
    );
  }

  // -------------------------------------------------------------------------
  // 渲染：审核项列表
  // -------------------------------------------------------------------------

  return (
    <div className={cn('flex flex-col gap-3 p-4', className)}>
      <AnimatePresence mode="popLayout">
        {items.map((item) => {
          /** 根据审核类型获取中文标签和样式 */
          const typeCfg = TYPE_CONFIG[item.type] || {
            label: item.type,
            badgeClass: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400',
          };

          /** 该审核项是否正在处理中 */
          const isProcessing = processingId === item.id;

          return (
            <motion.div
              key={item.id}
              layout
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, x: -40 }}
              transition={{ duration: 0.2 }}
              className="rounded-xl border border-border bg-card overflow-hidden"
            >
              <div className="p-4 space-y-3">
                {/* 审核项头部：类型标签 + 创建时间 */}
                <div className="flex items-center justify-between gap-3">
                  <span
                    className={cn(
                      'inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium',
                      typeCfg.badgeClass,
                    )}
                  >
                    {typeCfg.label}
                  </span>
                  <span className="text-xs text-muted-foreground shrink-0">
                    {new Date(item.createdAt).toLocaleString('zh-CN', {
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </span>
                </div>

                {/* 审核项内容描述 */}
                <p className="text-sm text-foreground leading-relaxed">{item.content}</p>

                {/* 建议操作说明 */}
                {item.action && (
                  <p className="text-xs text-muted-foreground">
                    <span className="font-medium text-foreground/70">建议操作：</span>
                    {item.action}
                  </p>
                )}

                {/* 操作按钮组 */}
                <div className="flex items-center gap-2 pt-1">
                  {/* 批准按钮 */}
                  <button
                    onClick={() => handleAction(item.id, 'approve')}
                    disabled={isProcessing}
                    className={cn(
                      'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all',
                      'bg-primary/10 text-primary hover:bg-primary/20',
                      'disabled:opacity-50 disabled:cursor-not-allowed',
                    )}
                  >
                    {isProcessing ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Check className="w-3.5 h-3.5" />
                    )}
                    批准
                  </button>

                  {/* 跳过按钮 */}
                  <button
                    onClick={() => handleAction(item.id, 'skip')}
                    disabled={isProcessing}
                    className={cn(
                      'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all',
                      'bg-muted text-muted-foreground hover:bg-muted/80 hover:text-foreground',
                      'disabled:opacity-50 disabled:cursor-not-allowed',
                    )}
                  >
                    <X className="w-3.5 h-3.5" />
                    跳过
                  </button>

                  {/* 删除按钮 */}
                  <button
                    onClick={() => handleAction(item.id, 'delete')}
                    disabled={isProcessing}
                    className={cn(
                      'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all',
                      'text-destructive/70 hover:text-destructive hover:bg-destructive/10',
                      'disabled:opacity-50 disabled:cursor-not-allowed',
                    )}
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    删除
                  </button>
                </div>
              </div>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
