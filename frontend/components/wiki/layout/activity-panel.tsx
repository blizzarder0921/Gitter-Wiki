'use client';

/**
 * 活动面板 -- activity-panel.tsx
 *
 * 底部或侧边活动面板，展示 Wiki 摄入（ingest）进度、
 * 最近操作日志和系统状态信息。
 *
 * 当前以摄入进度为主要展示内容，后续可扩展错误日志、
 * 处理统计等功能模块。
 */
import React from 'react';
import {
  Loader2,
  FileUp,
  CheckCircle2,
  AlertCircle,
  Clock,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Progress } from '@/components/ui/progress';
import type { IngestProgress } from '@/lib/wiki/types';

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------

/** ActivityPanel 组件属性 */
interface ActivityPanelProps {
  /** 摄入进度信息 */
  ingestProgress: IngestProgress | null;
  /** 是否正在摄入 */
  isIngesting: boolean;
  /** 重新摄入回调 */
  onStartIngest?: () => void;
  /** 自定义 className */
  className?: string;
}

// ---------------------------------------------------------------------------
// 组件实现
// ---------------------------------------------------------------------------

/**
 * 活动面板组件
 *
 * 展示文件摄入的实时进度，包括：
 * - 当前状态（空闲/运行中/完成/出错）
 * - 处理进度条（已处理 / 总数）
 * - 当前处理的文件名
 * - 错误信息（如有）
 *
 * 空闲状态下显示简易空状态引导。
 */
export function ActivityPanel({
  ingestProgress,
  isIngesting,
  onStartIngest,
  className,
}: ActivityPanelProps) {
  // 计算进度百分比
  const progressPercent =
    ingestProgress && ingestProgress.totalFiles > 0
      ? Math.round(
          (ingestProgress.processedFiles / ingestProgress.totalFiles) * 100,
        )
      : 0;

  return (
    <div
      className={cn(
        'flex flex-col h-full px-4 py-4',
        'bg-white/60 dark:bg-gray-800/60',
        className,
      )}
    >
      {/* 标题栏 */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
          活动状态
        </h3>
      </div>

      {/* 无活动：空闲状态 */}
      {!isIngesting && !ingestProgress && (
        <div className="flex flex-col items-center justify-center flex-1 text-center">
          <Clock className="w-8 h-8 text-gray-300 dark:text-gray-600 mb-2" />
          <p className="text-sm text-gray-400 dark:text-gray-500">
            暂无活动
          </p>
          <p className="text-xs text-gray-400/60 dark:text-gray-500/60 mt-1">
            摄入项目文件后将在此展示进度
          </p>
        </div>
      )}

      {/* 摄入进度 */}
      {(isIngesting || ingestProgress) && (
        <div className="flex-1">
          {/* 状态指示器 */}
          <div className="flex items-center gap-2 mb-3">
            {isIngesting ? (
              <>
                <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />
                <span className="text-sm text-blue-600 dark:text-blue-400">
                  正在处理文件...
                </span>
              </>
            ) : ingestProgress?.status === 'completed' ? (
              <>
                <CheckCircle2 className="w-4 h-4 text-green-500" />
                <span className="text-sm text-green-600 dark:text-green-400">
                  摄入完成
                </span>
              </>
            ) : ingestProgress?.status === 'error' ? (
              <>
                <AlertCircle className="w-4 h-4 text-red-500" />
                <span className="text-sm text-red-600 dark:text-red-400">
                  摄入出错
                </span>
              </>
            ) : null}
          </div>

          {/* 进度条 */}
          <div className="mb-2">
            <div className="flex items-center justify-between text-xs text-gray-400 mb-1.5">
              <span>处理进度</span>
              <span>
                {ingestProgress?.processedFiles ?? 0} /{' '}
                {ingestProgress?.totalFiles ?? 0}
              </span>
            </div>
            <Progress
              value={progressPercent}
              className="h-2"
            />
          </div>

          {/* 当前文件 */}
          {ingestProgress?.currentFile && (
            <div className="flex items-center gap-1.5 mt-3 text-xs text-gray-500 dark:text-gray-400">
              <FileUp className="w-3.5 h-3.5 flex-shrink-0" />
              <span className="truncate" title={ingestProgress.currentFile}>
                {ingestProgress.currentFile}
              </span>
            </div>
          )}

          {/* 错误信息 */}
          {ingestProgress?.errorMessage && (
            <div className="mt-3 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
              <div className="flex items-start gap-2">
                <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
                <p className="text-xs text-red-600 dark:text-red-400 break-words">
                  {ingestProgress.errorMessage}
                </p>
              </div>
            </div>
          )}

          {/* 完成统计 */}
          {ingestProgress?.status === 'completed' && (
            <div className="mt-4 p-3 rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800">
              <p className="text-xs text-green-600 dark:text-green-400">
                成功处理 {ingestProgress.processedFiles} 个文件
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default ActivityPanel;
