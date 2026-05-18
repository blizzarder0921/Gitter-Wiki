'use client';

import { motion } from 'motion/react';
import { Package, AlertCircle, Download, Loader2, FolderOpen } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { ExtractResult } from '@/lib/types/home';
import { getVersionTypeBadge } from '@/lib/utils/home';

/**
 * ExtractResult 组件属性
 * 展示压缩包解析后的项目信息及操作按钮
 */
interface ExtractResultProps {
  /** 压缩包解析结果 */
  result: ExtractResult;
  /** 是否正在添加项目 */
  addingProject: boolean;
  /** 确认添加新项目回调 */
  onConfirmAdd: () => void;
  /** 确认覆盖已有项目回调 */
  onConfirmOverwrite: () => void;
  /** 跳过该结果回调 */
  onSkip: () => void;
}

/**
 * 压缩包解析结果展示组件
 *
 * 在 Hero 区域显示 zip 解析后的项目信息：
 * - 项目名称与描述
 * - 版本类型徽章、版本号、GitHub URL
 * - 重复项目提示（含版本对比：相同/较新/较旧）
 * - 操作按钮：跳过 / 覆盖本地（重复且版本不同时） / 确认添加（新项目时）
 */
export function ExtractResult({ result, addingProject, onConfirmAdd, onConfirmOverwrite, onSkip }: ExtractResultProps) {
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
          <span className="font-semibold">{result.name}</span>
        </div>
        <p className="text-sm text-gray-600 dark:text-gray-300 mb-3">
          {result.description || '无描述'}
        </p>
        <div className="flex flex-wrap gap-4 text-xs text-gray-500 mb-3">
          {(() => {
            const badge = getVersionTypeBadge(result.versionType);
            return (
              <span className="flex items-center gap-1">
                版本类型: <badge.icon className={cn('w-3 h-3', badge.color)} />
                <span className="font-medium">{badge.label}</span>
              </span>
            );
          })()}
          <span>版本: <span className="font-medium">{result.versionInfo || '-'}</span></span>
          {result.githubUrl ? (
            <span>GitHub: <a href={result.githubUrl} target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline">{result.githubUrl}</a></span>
          ) : (
            <span className="flex items-center gap-1 text-amber-600 dark:text-amber-400">
              <FolderOpen className="w-3 h-3" />
              本地项目（无 GitHub 关联）
            </span>
          )}
        </div>

        {/* 重复项目提示 */}
        {result.duplicate.exists && result.duplicate.existingProject && (
          <div className={cn(
            'rounded-lg p-3 mb-3 text-sm',
            result.duplicate.versionComparison === 'same'
              ? 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300'
              : result.duplicate.versionComparison === 'newer'
              ? 'bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300'
              : result.duplicate.versionComparison === 'older'
              ? 'bg-yellow-50 dark:bg-yellow-900/20 text-yellow-700 dark:text-yellow-300'
              : 'bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300',
          )}>
            <div className="flex items-center gap-2 mb-1">
              <AlertCircle className="w-4 h-4" />
              <span className="font-medium">
                {result.duplicate.versionComparison === 'same'
                  ? '项目已存在，版本相同'
                  : result.duplicate.versionComparison === 'newer'
                  ? '压缩包版本较新'
                  : result.duplicate.versionComparison === 'older'
                  ? '压缩包是旧版本'
                  : '项目已存在，版本无法自动对比'}
              </span>
            </div>
            <div className="text-xs mt-1">
              本地版本: {result.duplicate.existingProject.current_version || result.duplicate.existingProject.latest_version || '未知'}
              {result.duplicate.existingProject.commit_sha && (
                <span className="ml-2 font-mono">({result.duplicate.existingProject.commit_sha.substring(0, 7)})</span>
              )}
            </div>
          </div>
        )}

        {/* 操作按钮 */}
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onSkip}>
            跳过
          </Button>
          {result.duplicate.exists ? (
            result.duplicate.versionComparison === 'same' ? null : (
              <Button size="sm" variant="destructive" onClick={onConfirmOverwrite} disabled={addingProject}>
                {addingProject ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : null}
                覆盖本地
              </Button>
            )
          ) : (
            <Button size="sm" className="!text-white" onClick={onConfirmAdd} disabled={addingProject}>
              {addingProject ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Download className="w-4 h-4 mr-1" />}
              确认添加
            </Button>
          )}
        </div>
      </div>
    </motion.div>
  );
}
