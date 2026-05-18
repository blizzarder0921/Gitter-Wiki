'use client';

/**
 * 文件预览面板 -- preview-panel.tsx
 *
 * 右侧面板，用于预览选中文件的内容。
 * - 无选中文件时显示空状态引导
 * - 有选中文件时使用 FilePreview 组件加载并渲染文件内容
 * - 右上角提供关闭按钮
 *
 * FilePreview 组件负责从 API 加载文件内容并根据文件类型渲染，
 * 本面板仅负责布局和关闭交互。
 */
import React from 'react';
import { X, FileText } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { FilePreview } from '@/components/wiki/editor/file-preview';

// ---------------------------------------------------------------------------
// Props 类型定义
// ---------------------------------------------------------------------------

/** 文件预览面板组件属性 */
interface PreviewPanelProps {
  /** 选中的文件路径 */
  filePath: string | null;
  /** 关闭预览回调 */
  onClose: () => void;
  /** 文件内容加载成功回调，用于同步内容到全局 store */
  onFileLoaded?: (content: string) => void;
}

// ---------------------------------------------------------------------------
// 组件实现
// ---------------------------------------------------------------------------

/**
 * 文件预览面板组件
 *
 * 无选中文件时显示空状态引导；
 * 有选中文件时使用 FilePreview 渲染文件内容，
 * 并在右上角提供关闭按钮。
 */
export function PreviewPanel({
  filePath,
  onClose,
  onFileLoaded,
}: PreviewPanelProps) {
  // 空状态：无选中文件
  if (!filePath) {
    return (
      <div className="flex flex-col items-center justify-center h-full px-4 py-12 text-center">
        <FileText className="w-10 h-10 text-gray-300 dark:text-gray-600 mb-3" />
        <p className="text-sm text-gray-400 dark:text-gray-500">
          选择左侧文件以预览内容
        </p>
        <p className="text-xs text-gray-400/60 dark:text-gray-500/60 mt-1 max-w-[200px]">
          点击文件树中的文件即可在此处查看内容
        </p>
      </div>
    );
  }

  return (
    <div className="relative flex flex-col h-full">
      {/* 关闭按钮 -- 绝对定位在右上角，覆盖在 FilePreview 头部之上 */}
      <div className="absolute top-0.5 right-0.5 z-10">
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          className="h-7 w-7 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
          aria-label="关闭预览"
        >
          <X className="w-4 h-4" />
        </Button>
      </div>

      {/* FilePreview 负责加载和渲染文件内容 */}
      <FilePreview
        filePath={filePath}
        onLoaded={onFileLoaded}
      />
    </div>
  );
}

export default PreviewPanel;
