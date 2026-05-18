'use client';

/**
 * 图标导航栏 -- icon-sidebar.tsx
 *
 * 左侧竖向图标导航，提供 Wiki 各视图的切换入口。
 * 使用 lucide-react 图标库，支持活跃态高亮与 Tooltip 提示。
 * 图标顺序（从上到下）：
 * 1. MessageCircle -- 对话视图
 * 2. FileText     -- 来源/文件视图
 * 3. GitGraph     -- 知识图谱视图
 * 4. CheckCircle2 -- 审核视图
 * 5. ClipboardList -- Lint 检查视图
 * 6. FlaskConical -- 研究视图
 */
import React from 'react';
import {
  MessageCircle,
  FileText,
  GitGraph,
  CheckCircle2,
  ClipboardList,
  FlaskConical,
  Heart,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import type { WikiView } from '@/lib/wiki/types';

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------

/** 导航项配置 */
interface NavItem {
  /** 视图标识 */
  view: WikiView;
  /** 图标组件 */
  icon: React.ComponentType<{ className?: string }>;
  /** 提示文本 */
  label: string;
}

/** 组件 Props */
interface IconSidebarProps {
  /** 当前激活的视图 */
  activeView: WikiView;
  /** 视图切换回调 */
  onViewChange: (view: WikiView) => void;
  /** 健康度评分（显示在底部） */
  healthScore?: number | null;
  /** 是否有待处理的审核项 */
  hasPendingReviews?: boolean;
  /** 是否有 Lint 问题 */
  hasLintIssues?: boolean;
}

// ---------------------------------------------------------------------------
// 常量定义
// ---------------------------------------------------------------------------

/** 导航项列表 -- 按垂直顺序排列 */
const NAV_ITEMS: NavItem[] = [
  { view: 'chat', icon: MessageCircle, label: 'AI 对话' },
  { view: 'sources', icon: FileText, label: '文件浏览' },
  { view: 'graph', icon: GitGraph, label: '知识图谱' },
  { view: 'review', icon: CheckCircle2, label: '审核' },
  { view: 'lint', icon: ClipboardList, label: 'Lint 检查' },
  { view: 'research', icon: FlaskConical, label: '深度研究' },
];

// ---------------------------------------------------------------------------
// 组件实现
// ---------------------------------------------------------------------------

/**
 * 图标导航栏组件
 *
 * 展示纵向排列的功能图标，每个图标对应一个 Wiki 视图。
 * 支持活跃态紫色高亮、审核/Lint 角标提示、底部健康度显示。
 */
export function IconSidebar({
  activeView,
  onViewChange,
  healthScore,
  hasPendingReviews,
  hasLintIssues,
}: IconSidebarProps) {
  return (
    <div className="flex flex-col items-center h-full py-3 gap-1">
      {/* 导航图标区 */}
      <div className="flex flex-col items-center gap-1 flex-1">
        {NAV_ITEMS.map((item) => {
          const isActive = activeView === item.view;

          // 审核项角标
          const showReviewBadge =
            item.view === 'review' && hasPendingReviews;
          // Lint 问题角标
          const showLintBadge =
            item.view === 'lint' && hasLintIssues;

          return (
            <Tooltip key={item.view}>
              <TooltipTrigger asChild>
                <button
                  onClick={() => onViewChange(item.view)}
                  className={cn(
                    'relative w-10 h-10 rounded-xl flex items-center justify-center transition-all duration-200',
                    isActive
                      ? 'bg-purple-100 dark:bg-purple-900/40 text-purple-600 dark:text-purple-400 shadow-sm'
                      : 'text-gray-400 dark:text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700/60 hover:text-gray-600 dark:hover:text-gray-300',
                  )}
                  aria-label={item.label}
                >
                  <item.icon className="w-5 h-5" />

                  {/* 审核角标 -- 橙色圆点 */}
                  {showReviewBadge && (
                    <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-orange-500 ring-1 ring-white dark:ring-gray-800" />
                  )}

                  {/* Lint 角标 -- 黄色圆点 */}
                  {showLintBadge && (
                    <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-yellow-500 ring-1 ring-white dark:ring-gray-800" />
                  )}
                </button>
              </TooltipTrigger>
              <TooltipContent side="right" sideOffset={8}>
                {item.label}
              </TooltipContent>
            </Tooltip>
          );
        })}
      </div>

      {/* 底部分隔线 */}
      <div className="w-8 h-px bg-gray-200 dark:bg-gray-700 my-1" />

      {/* 健康度评分显示 */}
      {healthScore !== undefined && healthScore !== null && (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              onClick={() => onViewChange('health')}
              className={cn(
                'w-10 h-10 rounded-xl flex items-center justify-center text-sm font-semibold transition-all duration-200',
                activeView === 'health'
                  ? 'bg-green-100 dark:bg-green-900/40 text-green-600 dark:text-green-400 shadow-sm'
                  : 'text-gray-400 dark:text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700/60',
              )}
              aria-label="健康度"
            >
              <Heart
                className={cn(
                  'w-4 h-4',
                  healthScore >= 80
                    ? 'text-green-500'
                    : healthScore >= 50
                      ? 'text-yellow-500'
                      : 'text-red-500',
                )}
              />
              <span className="text-[10px] ml-0.5">{healthScore}</span>
            </button>
          </TooltipTrigger>
          <TooltipContent side="right" sideOffset={8}>
            Wiki 健康度：{healthScore} 分
          </TooltipContent>
        </Tooltip>
      )}
    </div>
  );
}

export default IconSidebar;
