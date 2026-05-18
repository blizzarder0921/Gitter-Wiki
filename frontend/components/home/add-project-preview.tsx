'use client';

import { Fragment } from 'react';
import { motion } from 'motion/react';
import { Package, Download, Loader2, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { GithubInfo } from '@/lib/types/home';
import { WORKFLOW_LABELS } from '@/lib/types/home';
import { getVersionTypeBadge } from '@/lib/utils/home';

/**
 * AddProjectPreview 组件属性
 * 展示 GitHub 项目预览确认信息
 */
interface AddProjectPreviewProps {
  /** GitHub 项目预览信息 */
  previewInfo: GithubInfo;
  /** 是否正在添加项目 */
  addingProject: boolean;
  /** 添加项目的当前步骤编号 */
  addProjectStep: number;
  /** 后台工作流关联的项目 ID */
  workflowProjectId: number | null;
  /** 后台工作流当前状态 */
  workflowStatus: string;
  /** 本地存储路径 */
  localStoragePath: string;
  /** 确认添加项目回调 */
  onAddProject: () => void;
  /** 取消预览回调 */
  onCancel: () => void;
}

/**
 * GitHub 项目预览确认组件
 *
 * 在 Hero 区域显示项目预览信息：
 * - 项目名称与描述
 * - 版本类型徽章、最新版本号
 * - 本地存储路径预览
 * - README 前 200 字符预览
 * - 后台工作流进度条（克隆/构建图谱/抓取资源等）
 * - 工作流失败提示
 * - 步骤进度指示器（保存项目 -> 克隆到本地 -> 后台处理中）
 * - 取消 / 确认添加操作按钮
 */
export function AddProjectPreview({
  previewInfo,
  addingProject,
  addProjectStep,
  workflowProjectId,
  workflowStatus,
  localStoragePath,
  onAddProject,
  onCancel,
}: AddProjectPreviewProps) {
  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      className="mt-4 pt-4 border-t border-gray-100 dark:border-gray-700"
    >
      <div className="bg-gray-50 dark:bg-gray-800 rounded-xl p-4">
        <div className="flex items-center gap-2 mb-3">
          <Package className="w-5 h-5 text-purple-500" />
          <span className="font-semibold">{previewInfo.name}</span>
        </div>
        <p className="text-sm text-gray-600 dark:text-gray-300 mb-3">
          {previewInfo.description || '无描述'}
        </p>
        <div className="flex flex-wrap gap-4 text-xs text-gray-500 mb-3">
          {(() => {
            const badge = getVersionTypeBadge(previewInfo.versionType);
            return (
              <span className="flex items-center gap-1">
                版本类型: <badge.icon className={cn('w-3 h-3', badge.color)} />
                <span className="font-medium">{badge.label}</span>
              </span>
            );
          })()}
          <span>最新版本: <span className="font-medium">{previewInfo.latestVersion || '-'}</span></span>
        </div>
        {localStoragePath && (
          <div className="text-xs text-gray-500 mb-3">
            本地路径: <span className="font-mono">{localStoragePath.replace(/[\\/]$/, '')}\\{previewInfo.name}</span>
          </div>
        )}
        {previewInfo.readme && (
          <p className="text-xs text-gray-400 mb-3 line-clamp-2">
            {previewInfo.readme.substring(0, 200)}...
          </p>
        )}
        {/* 工作流进度 */}
        {workflowProjectId !== null && workflowStatus !== 'idle' && workflowStatus !== 'done' && (
          <div className="mb-3 p-3 rounded-lg bg-purple-50 dark:bg-purple-900/20 border border-purple-200 dark:border-purple-800">
            <div className="flex items-center gap-2 text-xs text-purple-700 dark:text-purple-300">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              <span>{WORKFLOW_LABELS[workflowStatus] || workflowStatus}</span>
            </div>
            <div className="mt-2 w-full bg-purple-200 dark:bg-purple-800 rounded-full h-1.5 overflow-hidden">
              <div className="bg-purple-500 h-full rounded-full transition-all duration-500 animate-pulse"
                style={{ width: workflowStatus === 'cloning' ? '20%' : workflowStatus === 'fetching_github' || workflowStatus === 'building_graph' ? '45%' : workflowStatus === 'bridging' ? '65%' : workflowStatus === 'compiling_wiki' ? '80%' : workflowStatus === 'cleaning_up' ? '95%' : '10%' }} />
            </div>
          </div>
        )}
        {workflowStatus === 'failed' && (
          <div className="mb-3 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
            <div className="flex items-center gap-2 text-xs text-red-700 dark:text-red-300">
              <X className="w-3.5 h-3.5" />
              <span>后台任务失败，可稍后重试</span>
            </div>
          </div>
        )}

        {/* 操作步骤进度条 */}
        <div className="text-xs text-gray-400 mb-3 flex items-center gap-1.5">
          {[
            { step: 1, label: '保存项目' },
            { step: 2, label: '克隆到本地' },
            { step: 3, label: '后台处理中...' },
          ].map((item, idx) => (
            <Fragment key={item.step}>
              {idx > 0 && (
                <span className={cn(
                  'text-gray-300 dark:text-gray-600 transition-colors',
                  addProjectStep >= item.step && 'text-purple-400 dark:text-purple-500',
                )}>→</span>
              )}
              <span className={cn(
                'inline-flex items-center justify-center w-4 h-4 rounded-full text-[10px] font-bold transition-colors',
                addProjectStep > item.step
                  ? 'bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400'
                  : addProjectStep === item.step
                    ? 'bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400'
                    : 'bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-500',
              )}>
                {addProjectStep > item.step ? '✓' : item.step}
              </span>
              <span className={cn(
                'transition-colors',
                addProjectStep >= item.step ? 'text-gray-700 dark:text-gray-300' : 'text-gray-400',
              )}>{item.label}</span>
            </Fragment>
          ))}
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onCancel}>
            取消
          </Button>
          <Button size="sm" className="!text-white" onClick={onAddProject} disabled={addingProject}>
            {addingProject ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Download className="w-4 h-4 mr-1" />}
            {localStoragePath ? '确认添加并下载' : '确认添加'}
          </Button>
        </div>
      </div>
    </motion.div>
  );
}
