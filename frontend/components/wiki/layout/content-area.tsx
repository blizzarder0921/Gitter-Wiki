'use client';

/**
 * 中间内容区 -- content-area.tsx
 *
 * Wiki 界面的核心展示区域，根据 activeView 切换不同子视图：
 * - chat     ：AI 对话面板
 * - sources  ：文件浏览视图（WikiReader 渲染选中文件内容）
 * - graph    ：知识图谱视图
 * - review   ：审核视图
 * - lint     ：Lint 检查视图
 * - research ：深度研究视图
 * - health   ：健康度仪表盘
 * - settings ：设置视图（待开发）
 *
 * 所有视图组件均为全局 Wiki 架构，无需 projectId 参数。
 */
import React from 'react';
import dynamic from 'next/dynamic';
import { FileSearch } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useWikiStore } from '@/stores/wiki-store';
import type { WikiView } from '@/lib/wiki/types';
import { ChatPanel } from '@/components/wiki/chat/chat-panel';
import { ReviewView } from '@/components/wiki/review/review-view';
import { LintView } from '@/components/wiki/lint/lint-view';
import { ResearchPanel } from '@/components/wiki/research/research-panel';
import { HealthDashboard } from '@/components/wiki/health/health-dashboard';
import { WikiReader } from '@/components/wiki/editor/wiki-reader';

/** 动态导入 GraphView，禁用 SSR（vis-network 依赖 DOM） */
const GraphView = dynamic(
  () => import('@/components/wiki/graph/graph-view').then((mod) => mod.GraphView),
  { ssr: false, loading: () => <div className="flex items-center justify-center h-full text-sm text-gray-400">正在加载图谱组件...</div> },
);

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------

/** ContentArea 组件属性 */
interface ContentAreaProps {
  /** 当前激活的视图 */
  activeView: WikiView;
  /** 点击搜索结果/图谱节点时设置选中的文件路径 */
  onSelectFile?: (path: string) => void;
  /** 自定义 className */
  className?: string;
}

// ---------------------------------------------------------------------------
// 子组件：来源视图（无文件选中时的引导页）
// ---------------------------------------------------------------------------

/** 文件浏览视图的空状态引导 */
function SourcesPlaceholder() {
  return (
    <div className="flex flex-col items-center justify-center h-full px-6 py-12 text-center">
      <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-purple-500/20 to-blue-500/20 flex items-center justify-center mb-4">
        <FileSearch className="w-8 h-8 text-purple-400" />
      </div>
      <h2 className="text-lg font-semibold text-gray-700 dark:text-gray-300 mb-1">
        文件浏览
      </h2>
      <p className="text-sm text-gray-400 dark:text-gray-500 max-w-sm">
        请从左侧文件树中选择一个文件以查看其内容
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 组件实现
// ---------------------------------------------------------------------------

/**
 * 中间内容区组件
 *
 * 根据 activeView 渲染对应的功能视图。
 * 全局 Wiki 架构，无需 projectId。
 */
export function ContentArea({ activeView, onSelectFile, className }: ContentAreaProps) {
  const selectedFile = useWikiStore((s) => s.selectedFile);
  const fileContent = useWikiStore((s) => s.fileContent);

  switch (activeView) {
    case 'chat':
      return <ChatPanel />;

    case 'sources':
      if (selectedFile && fileContent) {
        return (
          <div className={cn('h-full overflow-auto', className)}>
            <WikiReader content={fileContent} />
          </div>
        );
      }
      return (
        <div className={cn('h-full', className)}>
          <SourcesPlaceholder />
        </div>
      );

    case 'graph':
      return (
        <GraphView
          onSelectFile={onSelectFile}
          className={cn('h-full', className)}
        />
      );

    case 'review':
      return (
        <ReviewView
          className={cn('h-full', className)}
        />
      );

    case 'lint':
      return (
        <LintView
          onNavigate={onSelectFile}
        />
      );

    case 'research':
      return <ResearchPanel />;

    case 'health':
      return (
        <HealthDashboard
          className={cn('h-full', className)}
        />
      );

    case 'settings':
    default:
      return (
        <div className={cn(
          'flex flex-col items-center justify-center h-full px-6 py-12 text-center',
          className,
        )}
        >
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-purple-500/20 to-blue-500/20 flex items-center justify-center mb-4">
            <span className="text-2xl font-bold bg-gradient-to-r from-purple-600 to-blue-600 bg-clip-text text-transparent">
              W
            </span>
          </div>
          <h2 className="text-lg font-semibold text-gray-700 dark:text-gray-300 mb-1">
            设置
          </h2>
          <p className="text-sm text-gray-400 dark:text-gray-500 max-w-sm">
            Wiki 设置请通过首页右上角的全局设置进行配置
          </p>
        </div>
      );
  }
}

export default ContentArea;
