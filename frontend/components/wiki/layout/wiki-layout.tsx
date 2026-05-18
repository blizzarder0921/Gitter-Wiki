'use client';

/**
 * Wiki 三栏布局容器 -- wiki-layout.tsx
 *
 * 定义 Wiki 界面的整体布局结构：
 * - 顶部导航栏（返回按钮 + 项目名称，可选显示）
 * - 左侧图标导航栏（48px 固定宽度）
 * - 侧边面板（文件树/知识树，可折叠）
 * - 中间主内容区（弹性宽度）
 * - 右侧预览面板（可折叠）
 *
 * 遵循 Gitter 项目的设计风格：半透明毛玻璃背景、
 * 细边框分隔、紫色/蓝色渐变点缀。
 */
import React from 'react';
import { ArrowLeft } from 'lucide-react';
import Link from 'next/link';
import { cn } from '@/lib/utils';

// ---------------------------------------------------------------------------
// Props 类型定义
// ---------------------------------------------------------------------------

/** WikiLayout 组件的属性 */
interface WikiLayoutProps {
  /** 左侧图标导航栏内容 */
  iconSidebar: React.ReactNode;
  /** 侧边面板内容（文件树等） */
  sidebarPanel: React.ReactNode | null;
  /** 中间主内容区 */
  children: React.ReactNode;
  /** 右侧预览面板内容 */
  previewPanel: React.ReactNode | null;
  /** 侧边面板是否展开 */
  sidebarOpen?: boolean;
  /** 预览面板是否展开 */
  previewOpen?: boolean;
  /** 返回按钮的跳转地址 */
  backHref?: string;
  /** 顶部栏标题（如项目名称） */
  topBarTitle?: string;
  /** 自定义 className */
  className?: string;
}

// ---------------------------------------------------------------------------
// 组件实现
// ---------------------------------------------------------------------------

/**
 * Wiki 三栏布局容器
 *
 * 使用 CSS Flexbox 实现自适应三栏布局：
 * - 顶部导航栏 40px 高（有 backHref 时显示）
 * - 图标导航固定 56px 宽，始终可见
 * - 侧边面板 256px 宽，通过 sidebarOpen 控制显示
 * - 主内容区 flex-1 填充剩余空间
 * - 预览面板 320px 宽，通过 previewOpen 控制显示
 */
export function WikiLayout({
  iconSidebar,
  sidebarPanel,
  children,
  previewPanel,
  sidebarOpen = true,
  previewOpen = false,
  backHref,
  topBarTitle,
  className,
}: WikiLayoutProps) {
  return (
    <div
      className={cn(
        'flex flex-col h-full w-full overflow-hidden',
        className,
      )}
    >
      {/* 顶部导航栏 -- 有返回按钮时显示 */}
      {backHref && (
        <div className="flex-shrink-0 h-10 flex items-center gap-2 px-3 border-b border-gray-200/60 dark:border-gray-700/60 bg-white/60 dark:bg-gray-800/60 backdrop-blur-sm">
          <Link
            href={backHref}
            className="flex items-center gap-1.5 px-2 py-1 rounded-lg text-sm text-gray-500 dark:text-gray-400 hover:text-purple-600 dark:hover:text-purple-400 hover:bg-purple-50 dark:hover:bg-purple-900/20 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>返回</span>
          </Link>
          {topBarTitle && (
            <>
              <span className="w-px h-4 bg-gray-200 dark:bg-gray-600" />
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300 truncate">
                {topBarTitle}
              </span>
            </>
          )}
        </div>
      )}

      {/* 主体三栏区域 */}
      <div className="flex flex-1 min-h-0 overflow-hidden bg-gradient-to-b from-slate-50 to-slate-100 dark:from-slate-950 dark:to-slate-900">
        {/* 左侧图标导航栏 -- 固定宽度 56px */}
        <div className="flex-shrink-0 w-14 border-r border-gray-200/60 dark:border-gray-700/60 bg-white/40 dark:bg-gray-800/40 backdrop-blur-sm overflow-hidden">
          {iconSidebar}
        </div>

        {/* 侧边面板 -- 256px，可折叠 */}
        {sidebarPanel !== null && sidebarOpen && (
          <div className="flex-shrink-0 w-64 border-r border-gray-200/60 dark:border-gray-700/60 bg-white/40 dark:bg-gray-800/40 backdrop-blur-sm overflow-hidden">
            {sidebarPanel}
          </div>
        )}

        {/* 中间主内容区 -- 弹性填充 */}
        <div className="flex-1 min-w-0 overflow-hidden">
          {children}
        </div>

        {/* 右侧预览面板 -- 320px，可折叠 */}
        {previewPanel !== null && previewOpen && (
          <div className="flex-shrink-0 w-80 border-l border-gray-200/60 dark:border-gray-700/60 bg-white/60 dark:bg-gray-800/60 backdrop-blur-sm overflow-hidden">
            {previewPanel}
          </div>
        )}
      </div>
    </div>
  );
}

export default WikiLayout;
