'use client';

/**
 * 全局 Wiki 入口页面 -- app/wiki/page.tsx
 *
 * Wiki 的统一入口页面，无需 projectId 参数。
 * 页面加载时直接调用全局 API 获取文件树、状态和对话列表。
 *
 * 页面功能：
 * - 加载 Wiki 状态（健康度）
 * - 加载文件树
 * - 加载对话列表
 * - 渲染三栏布局（图标导航 + 文件树 + 内容区 + 预览面板）
 *
 * 使用 zustand store 管理全局状态，API 调用统一通过 store 方法。
 */
import React, { useEffect, useCallback, useState } from 'react';
import { WikiLayout } from '@/components/wiki/layout/wiki-layout';
import { IconSidebar } from '@/components/wiki/layout/icon-sidebar';
import { SidebarPanel } from '@/components/wiki/layout/sidebar-panel';
import { ContentArea } from '@/components/wiki/layout/content-area';
import { PreviewPanel } from '@/components/wiki/layout/preview-panel';
import { useWikiStore } from '@/stores/wiki-store';
import { useChatStore } from '@/stores/chat-store';
import { useReviewStore } from '@/stores/review-store';
import { Loader2 } from 'lucide-react';
import type { WikiView } from '@/lib/wiki/types';

// ---------------------------------------------------------------------------
// 主页面组件
// ---------------------------------------------------------------------------

/**
 * 全局 Wiki 入口页面
 *
 * 路由匹配 `/wiki`。
 * 无需 projectId，直接加载全局 Wiki 数据并渲染三栏布局。
 */
export default function WikiPage() {
  // ---- zustand stores ----
  const {
    fileTree,
    selectedFile,
    activeView,
    healthScore,
    loading,
    setSelectedFile,
    setFileContent,
    setActiveView,
    loadFileTree,
    loadStatus,
    refreshKnowledge,
  } = useWikiStore();

  const { loadConversations } = useChatStore();
  const { items: reviewItems } = useReviewStore();

  // 预览面板展开/收起
  const [previewOpen, setPreviewOpen] = useState(false);

  // -----------------------------------------------------------------------
  // 初始化：加载全局 Wiki 数据
  // -----------------------------------------------------------------------

  useEffect(() => {
    // 并行加载 Wiki 状态、文件树和对话列表
    loadStatus().catch(() => {});
    loadFileTree().catch(() => {});
    loadConversations().catch(() => {});
  }, [loadStatus, loadFileTree, loadConversations]);

  // -----------------------------------------------------------------------
  // 当选中文件变化时自动打开预览面板
  // -----------------------------------------------------------------------

  useEffect(() => {
    if (selectedFile) {
      setPreviewOpen(true);
    }
  }, [selectedFile]);

  // -----------------------------------------------------------------------
  // 事件处理
  // -----------------------------------------------------------------------

  /** 切换视图面板 */
  const handleViewChange = useCallback(
    (view: WikiView) => {
      setActiveView(view);
    },
    [setActiveView],
  );

  /** 选中文件 */
  const handleSelectFile = useCallback(
    (path: string) => {
      setSelectedFile(path);
    },
    [setSelectedFile],
  );

  /** FilePreview 加载文件内容成功回调，同步到全局 store */
  const handleFileLoaded = useCallback(
    (content: string) => {
      setFileContent(content);
    },
    [setFileContent],
  );

  /** 关闭预览 */
  const handleClosePreview = useCallback(() => {
    setPreviewOpen(false);
  }, []);

  // -----------------------------------------------------------------------
  // 加载中 -- 显示 Loading 状态
  // -----------------------------------------------------------------------

  if (loading && fileTree.length === 0) {
    return (
      <div className="flex items-center justify-center h-[100dvh] w-full bg-gradient-to-b from-slate-50 to-slate-100 dark:from-slate-950 dark:to-slate-900">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-8 h-8 text-purple-500 animate-spin" />
          <p className="text-sm text-gray-400">正在加载 Wiki 数据...</p>
        </div>
      </div>
    );
  }

  // -----------------------------------------------------------------------
  // 正常渲染 -- 三栏布局
  // -----------------------------------------------------------------------

  // 计算审核项角标标识
  const hasPendingReviews = reviewItems.some((item) => !item.resolved);
  const hasLintIssues = false; // 后续集成 Lint Store 后动态计算

  return (
    <WikiLayout
      backHref="/"
      topBarTitle="Wiki 知识库"
      iconSidebar={
        <IconSidebar
          activeView={activeView}
          onViewChange={handleViewChange}
          healthScore={healthScore?.score}
          hasPendingReviews={hasPendingReviews}
          hasLintIssues={hasLintIssues}
        />
      }
      sidebarPanel={
        <SidebarPanel
          fileTree={fileTree}
          selectedFile={selectedFile}
          onSelectFile={handleSelectFile}
          activeView={activeView}
          onViewChange={handleViewChange}
          loading={loading}
          onRefreshKnowledge={refreshKnowledge}
        />
      }
      sidebarOpen={true}
      previewPanel={
        <PreviewPanel
          filePath={selectedFile}
          onClose={handleClosePreview}
          onFileLoaded={handleFileLoaded}
        />
      }
      previewOpen={previewOpen}
    >
      <ContentArea
        activeView={activeView}
        onSelectFile={handleSelectFile}
      />
    </WikiLayout>
  );
}
