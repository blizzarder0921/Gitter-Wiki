'use client';

/**
 * Wiki 健康度仪表板组件 -- health-dashboard.tsx
 *
 * 从 /api/wiki/status 获取 Wiki 的健康度数据，
 * 以综合评分圆环 + 指标卡片网格 + 历史趋势柱状图的形式展示。
 *
 * 数据来源：GET /api/wiki/status
 *
 * 依赖：
 *   - lucide-react：图表相关图标
 *   - motion/react：动画效果
 */

import { useEffect, useState, useCallback, useMemo } from 'react';
import { motion } from 'motion/react';
import {
  Loader2,
  Activity,
  GitGraph,
  GitFork,
  Link2Off,
  Link,
  Clock,
  TrendingUp,
  TrendingDown,
} from 'lucide-react';
import { cn } from '@/lib/utils';

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------

/** 组件 Props */
interface HealthDashboardProps {
  /** 自定义类名 */
  className?: string;
}

/** 健康度快照数据结构（来自 API 响应） */
interface HealthSnapshot {
  score: number;
  nodeCount: number;
  edgeCount: number;
  isolatedPages: number;
  brokenLinks: number;
  outdatedConcepts: number;
  createdAt: string;
}

/** 历史趋势数据点 */
interface TrendPoint {
  score: number;
  nodeCount: number;
  edgeCount: number;
  isolatedPages: number;
  brokenLinks: number;
  outdatedConcepts: number;
  createdAt: string;
}

/** /api/wiki/status 的完整响应结构 */
interface StatusResponse {
  healthSnapshot: HealthSnapshot | null;
  healthTrend: TrendPoint[];
  graphSummary: {
    nodeCount: number;
    edgeCount: number;
    communityCount: number;
  } | null;
}

// ---------------------------------------------------------------------------
// 指标卡片配置
// ---------------------------------------------------------------------------

/** 单项健康度指标的展示配置 */
interface MetricConfig {
  /** 数据字段键名 */
  key: keyof Pick<HealthSnapshot, 'nodeCount' | 'edgeCount' | 'isolatedPages' | 'brokenLinks' | 'outdatedConcepts'>;
  /** 中文标签 */
  label: string;
  /** 图标组件 */
  icon: typeof GitGraph;
  /**
   * 颜色方案判定函数
   * 返回 tailwind 颜色类名（text/background），用于卡片底色与文字色
   */
  color: (value: number) => { bg: string; text: string; border: string };
}

/**
 * 指标卡片定义列表
 * 每个指标根据数值范围映射不同颜色：
 *   - 绿色：健康范围（节点/边越多越好，孤立/断链/过时越少越好）
 *   - 黄色：警告范围（中等偏离理想值）
 *   - 红色：危险范围（严重偏离理想值）
 */
const METRIC_CONFIGS: MetricConfig[] = [
  {
    key: 'nodeCount',
    label: '节点数',
    icon: GitGraph,
    color: (v: number) => {
      if (v >= 50) return { bg: 'bg-emerald-50 dark:bg-emerald-950/40', text: 'text-emerald-700 dark:text-emerald-400', border: 'border-emerald-200 dark:border-emerald-800' };
      if (v >= 10) return { bg: 'bg-yellow-50 dark:bg-yellow-950/40', text: 'text-yellow-700 dark:text-yellow-400', border: 'border-yellow-200 dark:border-yellow-800' };
      return { bg: 'bg-red-50 dark:bg-red-950/40', text: 'text-red-700 dark:text-red-400', border: 'border-red-200 dark:border-red-800' };
    },
  },
  {
    key: 'edgeCount',
    label: '边数',
    icon: GitFork,
    color: (v: number) => {
      if (v >= 80) return { bg: 'bg-emerald-50 dark:bg-emerald-950/40', text: 'text-emerald-700 dark:text-emerald-400', border: 'border-emerald-200 dark:border-emerald-800' };
      if (v >= 15) return { bg: 'bg-yellow-50 dark:bg-yellow-950/40', text: 'text-yellow-700 dark:text-yellow-400', border: 'border-yellow-200 dark:border-yellow-800' };
      return { bg: 'bg-red-50 dark:bg-red-950/40', text: 'text-red-700 dark:text-red-400', border: 'border-red-200 dark:border-red-800' };
    },
  },
  {
    key: 'isolatedPages',
    label: '孤立页面',
    icon: Link2Off,
    color: (v: number) => {
      if (v === 0) return { bg: 'bg-emerald-50 dark:bg-emerald-950/40', text: 'text-emerald-700 dark:text-emerald-400', border: 'border-emerald-200 dark:border-emerald-800' };
      if (v <= 3) return { bg: 'bg-yellow-50 dark:bg-yellow-950/40', text: 'text-yellow-700 dark:text-yellow-400', border: 'border-yellow-200 dark:border-yellow-800' };
      return { bg: 'bg-red-50 dark:bg-red-950/40', text: 'text-red-700 dark:text-red-400', border: 'border-red-200 dark:border-red-800' };
    },
  },
  {
    key: 'brokenLinks',
    label: '断链数',
    icon: Link,
    color: (v: number) => {
      if (v === 0) return { bg: 'bg-emerald-50 dark:bg-emerald-950/40', text: 'text-emerald-700 dark:text-emerald-400', border: 'border-emerald-200 dark:border-emerald-800' };
      if (v <= 5) return { bg: 'bg-yellow-50 dark:bg-yellow-950/40', text: 'text-yellow-700 dark:text-yellow-400', border: 'border-yellow-200 dark:border-yellow-800' };
      return { bg: 'bg-red-50 dark:bg-red-950/40', text: 'text-red-700 dark:text-red-400', border: 'border-red-200 dark:border-red-800' };
    },
  },
  {
    key: 'outdatedConcepts',
    label: '过时概念',
    icon: Clock,
    color: (v: number) => {
      if (v === 0) return { bg: 'bg-emerald-50 dark:bg-emerald-950/40', text: 'text-emerald-700 dark:text-emerald-400', border: 'border-emerald-200 dark:border-emerald-800' };
      if (v <= 3) return { bg: 'bg-yellow-50 dark:bg-yellow-950/40', text: 'text-yellow-700 dark:text-yellow-400', border: 'border-yellow-200 dark:border-yellow-800' };
      return { bg: 'bg-red-50 dark:bg-red-950/40', text: 'text-red-700 dark:text-red-400', border: 'border-red-200 dark:border-red-800' };
    },
  },
];

// ---------------------------------------------------------------------------
// 辅助函数
// ---------------------------------------------------------------------------

/**
 * 根据健康度评分返回对应的颜色类名
 * 90-100：绿色（优秀），70-89：黄色（良好），0-69：红色（需关注）
 */
function getScoreColor(score: number): { ring: string; text: string; bg: string } {
  if (score >= 90) return { ring: 'stroke-emerald-500', text: 'text-emerald-600 dark:text-emerald-400', bg: 'bg-emerald-500/10' };
  if (score >= 70) return { ring: 'stroke-yellow-500', text: 'text-yellow-600 dark:text-yellow-400', bg: 'bg-yellow-500/10' };
  return { ring: 'stroke-red-500', text: 'text-red-600 dark:text-red-400', bg: 'bg-red-500/10' };
}

/**
 * 根据健康度评分返回趋势图标
 * 对比最新评分与上一评分，判断上升或下降趋势
 */
function getTrendIcon(currentScore: number, previousScore: number | undefined) {
  if (previousScore === undefined || currentScore === previousScore) return null;
  if (currentScore > previousScore) {
    return <TrendingUp className="w-4 h-4 text-emerald-500" />;
  }
  return <TrendingDown className="w-4 h-4 text-red-500" />;
}

// ---------------------------------------------------------------------------
// 子组件：圆形评分环
// ---------------------------------------------------------------------------

/**
 * 圆形进度环组件
 * 使用 SVG 绘制环形进度条，中央显示评分数字
 *
 * @param score - 0-100 的评分值
 * @param size - 圆环直径（像素）
 */
function ScoreRing({ score, size = 140 }: { score: number; size?: number }) {
  const strokeWidth = 8;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  /** 根据评分计算已填充的弧长 */
  const filledLength = (score / 100) * circumference;

  const { ring, text, bg } = getScoreColor(score);

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      {/* 背景圆环 */}
      <svg width={size} height={size} className="absolute -rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          className="text-muted-foreground/15"
        />
      </svg>
      {/* 前景进度圆环 */}
      <motion.svg
        width={size}
        height={size}
        className="absolute -rotate-90"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.5 }}
      >
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          className={ring}
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: circumference - filledLength }}
          transition={{ duration: 1, ease: 'easeOut' }}
        />
      </motion.svg>
      {/* 中央文字 */}
      <div className="flex flex-col items-center">
        <motion.span
          className={cn('text-4xl font-bold', text)}
          initial={{ scale: 0.5, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ delay: 0.3, duration: 0.5 }}
        >
          {score}
        </motion.span>
        <span className="text-xs text-muted-foreground mt-0.5">综合评分</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 子组件：历史趋势柱状图
// ---------------------------------------------------------------------------

/**
 * 简易柱状趋势图
 * 展示最近 N 次健康度快照的评分变化趋势
 */
function TrendChart({ trend }: { trend: TrendPoint[] }) {
  /** 只展示最近 10 条，且 reverse 为按时间升序 */
  const data = useMemo(() => {
    return [...trend].slice(0, 10).reverse();
  }, [trend]);

  if (data.length < 2) return null;

  /** 计算趋势数据范围，用于柱状图高度归一化 */
  const maxScore = Math.max(...data.map((d) => d.score), 1);
  const minScore = Math.min(...data.map((d) => d.score), 0);

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="p-4 space-y-3">
        {/* 标题行 */}
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-muted-foreground" />
          <h3 className="text-sm font-semibold">评分趋势</h3>
          {getTrendIcon(data[data.length - 1]?.score, data[data.length - 2]?.score)}
        </div>
        {/* 柱状图容器 */}
        <div className="flex items-end gap-1.5 h-24">
          {data.map((point, index) => {
            /** 柱高占最大高度的百分比，最小 4% 避免完全不可见 */
            const heightPct = Math.max(4, ((point.score - minScore) / Math.max(maxScore - minScore, 1)) * 100);
            const isLast = index === data.length - 1;
            return (
              <div key={point.createdAt} className="flex-1 flex flex-col items-center gap-1 min-w-0">
                <motion.div
                  className={cn(
                    'w-full rounded-t-sm',
                    isLast
                      ? 'bg-primary'
                      : 'bg-primary/30',
                  )}
                  initial={{ height: 0 }}
                  animate={{ height: `${heightPct}%` }}
                  transition={{ duration: 0.5, delay: index * 0.05 }}
                />
                {/* 日期标签，仅显示首尾及中间少数几个点 */}
                {(index === 0 || index === data.length - 1 || index === Math.floor(data.length / 2)) && (
                  <span className="text-[10px] text-muted-foreground truncate w-full text-center">
                    {new Date(point.createdAt).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 主组件
// ---------------------------------------------------------------------------

/**
 * Wiki 健康度仪表板
 *
 * 从服务端获取 Wiki 项目的健康度数据，以综合评分圆环、指标卡片网格
 * 和历史趋势柱状图的形式直观展示 Wiki 知识库质量。
 */
export function HealthDashboard({ className }: HealthDashboardProps) {
  /** 健康度数据 */
  const [data, setData] = useState<StatusResponse | null>(null);
  /** 加载状态 */
  const [loading, setLoading] = useState(true);
  /** 错误信息 */
  const [error, setError] = useState<string | null>(null);

  /**
   * 从服务端加载健康度数据
   */
  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/wiki/status');
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error || '获取健康度数据失败');
      }
      const result: StatusResponse = await res.json();
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : '未知错误');
    } finally {
      setLoading(false);
    }
  }, []);

  /** 组件挂载时加载数据 */
  useEffect(() => {
    fetchData();
  }, [fetchData]);

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
          onClick={fetchData}
          className="text-xs text-primary hover:underline transition-colors"
        >
          点击重试
        </button>
      </div>
    );
  }

  // -------------------------------------------------------------------------
  // 渲染：空状态（没有 healthSnapshot 数据）
  // -------------------------------------------------------------------------

  if (!data || !data.healthSnapshot) {
    return (
      <div className={cn('flex flex-col items-center justify-center py-16 gap-3 text-muted-foreground', className)}>
        <Activity className="w-12 h-12 opacity-30" />
        <p className="text-sm">暂无健康度数据</p>
        <p className="text-xs">完成首次 Wiki 摄入后可查看健康度评分</p>
      </div>
    );
  }

  /** 解构快照数据，捕获为局部常量避免闭包中类型缩窄丢失 */
  const snapshot = data.healthSnapshot;
  const { score } = snapshot;

  return (
    <div className={cn('flex flex-col gap-6 p-4', className)}>
      {/* 综合评分区域 */}
      <div className="flex flex-col items-center gap-3">
        <ScoreRing score={score} size={140} />
        <div className="flex items-center gap-2">
          {getTrendIcon(
            score,
            data.healthTrend.length > 1 ? data.healthTrend[data.healthTrend.length - 2]?.score : undefined,
          )}
          <span className="text-xs text-muted-foreground">
            最近更新：
            {new Date(snapshot.createdAt).toLocaleString('zh-CN', {
              month: 'long',
              day: 'numeric',
              hour: '2-digit',
              minute: '2-digit',
            })}
          </span>
        </div>
      </div>

      {/* 指标卡片网格 */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {METRIC_CONFIGS.map((metric) => {
          /** 从快照中获取当前指标数值 */
          const value = snapshot[metric.key] as number;
          const colors = metric.color(value);
          const IconComp = metric.icon;

          return (
            <motion.div
              key={metric.key}
              className={cn(
                'rounded-xl border p-3 flex flex-col gap-1.5 transition-colors',
                colors.bg,
                colors.border,
              )}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3 }}
            >
              {/* 图标 + 标签 */}
              <div className="flex items-center gap-1.5">
                <IconComp className={cn('w-3.5 h-3.5', colors.text)} />
                <span className="text-xs text-muted-foreground">{metric.label}</span>
              </div>
              {/* 数值 */}
              <span className={cn('text-2xl font-bold', colors.text)}>
                {value.toLocaleString()}
              </span>
            </motion.div>
          );
        })}
      </div>

      {/* 历史趋势图 */}
      {data.healthTrend && data.healthTrend.length > 1 && (
        <TrendChart trend={data.healthTrend} />
      )}
    </div>
  );
}
