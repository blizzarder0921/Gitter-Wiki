'use client';

import { motion } from 'motion/react';
import { Search, Check, X, Download, Loader2, AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { cn } from '@/lib/utils';
import type { BatchExtractResult, RepoAddStatus } from '@/lib/types/home';

/**
 * BatchExtractResult 组件属性
 * 展示批量提取到的 GitHub 仓库列表及批量操作
 */
interface BatchExtractResultProps {
  /** 批量提取结果数据 */
  results: BatchExtractResult;
  /** 当前选中的仓库 URL 集合 */
  selectedRepos: Set<string>;
  /** 选中仓库变更回调 */
  onSelectedReposChange: (repos: Set<string>) => void;
  /** 是否正在批量添加仓库 */
  addingRepos: boolean;
  /** 各仓库的添加状态记录 */
  repoAddStatus: Record<string, RepoAddStatus>;
  /** 批量添加回调 */
  onBatchAdd: () => void;
  /** 关闭结果面板回调 */
  onClose: () => void;
}

/**
 * 批量提取结果展示组件
 *
 * 显示从文章链接 / 图片 OCR 中提取到的仓库列表：
 * - 每行显示仓库名、状态标签（已添加/添加中/已成功/失败）、描述、URL、来源
 * - 每行带复选框（已存在于数据库中则禁用）
 * - 底部显示关闭 / 批量添加按钮
 */
export function BatchExtractResult({
  results,
  selectedRepos,
  onSelectedReposChange,
  addingRepos,
  repoAddStatus,
  onBatchAdd,
  onClose,
}: BatchExtractResultProps) {
  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      className="mt-4 pt-4 border-t border-gray-100 dark:border-gray-700"
    >
      <div className="bg-gray-50 dark:bg-gray-800 rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Search className="w-5 h-5 text-purple-500" />
            <span className="font-semibold">提取结果</span>
          </div>
          <span className="text-xs text-gray-400">
            共发现 {results.total} 个仓库，{results.success} 个有效
          </span>
        </div>

        <div className="space-y-2 mb-3">
          {/* 失败项错误提示 */}
          {results.results?.filter((r) => r.status === 'failed' && r.error).map((r, idx) => (
            <div
              key={`err-${idx}`}
              className="flex items-start gap-2 p-3 rounded-lg border border-yellow-200 dark:border-yellow-800 bg-yellow-50 dark:bg-yellow-900/20"
            >
              <AlertTriangle className="w-4 h-4 text-yellow-500 shrink-0 mt-0.5" />
              <div className="min-w-0">
                <p className="text-sm font-medium text-yellow-700 dark:text-yellow-400">
                  {r.type === 'image' ? '图片识别失败' : '提取失败'}：{r.input}
                </p>
                <p className="text-xs text-yellow-600 dark:text-yellow-500 mt-0.5 leading-relaxed">
                  {r.error}
                </p>
              </div>
            </div>
          ))}
          {results.repos.map((repo) => (
            <div
              key={repo.url}
              className={cn(
                'flex items-start gap-3 p-3 rounded-lg border transition-colors',
                repo.existsInDb
                  ? 'bg-gray-50 dark:bg-gray-700/50 border-gray-200 dark:border-gray-600'
                  : selectedRepos.has(repo.url)
                  ? 'bg-purple-50 dark:bg-purple-900/20 border-purple-300 dark:border-purple-600'
                  : 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700',
              )}
            >
              <Checkbox
                checked={selectedRepos.has(repo.url)}
                disabled={repo.existsInDb}
                onCheckedChange={(checked) => {
                  const next = new Set(selectedRepos);
                  if (checked) next.add(repo.url);
                  else next.delete(repo.url);
                  onSelectedReposChange(next);
                }}
                className="mt-0.5"
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm truncate">{repo.name}</span>
                  {repo.existsInDb && (
                    <span className="text-xs px-1.5 py-0.5 rounded-full bg-gray-200 dark:bg-gray-600 text-gray-500 dark:text-gray-400">
                      已添加
                    </span>
                  )}
                  {repoAddStatus[repo.url] === 'adding' && (
                    <span className="text-xs px-1.5 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 flex items-center gap-1">
                      <Loader2 className="w-3 h-3 animate-spin" />
                      添加中
                    </span>
                  )}
                  {repoAddStatus[repo.url] === 'success' && (
                    <span className="text-xs px-1.5 py-0.5 rounded-full bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400 flex items-center gap-1">
                      <Check className="w-3 h-3" />
                      已成功
                    </span>
                  )}
                  {repoAddStatus[repo.url] === 'failed' && (
                    <span className="text-xs px-1.5 py-0.5 rounded-full bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 flex items-center gap-1">
                      <X className="w-3 h-3" />
                      失败
                    </span>
                  )}
                </div>
                <p className="text-xs text-gray-500 dark:text-gray-400 truncate mt-0.5">
                  {repo.description || '无描述'}
                </p>
                <div className="flex items-center gap-2 mt-0.5">
                  <a
                    href={repo.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-blue-500 hover:underline truncate"
                  >
                    {repo.url}
                  </a>
                  {repo.sources.length > 0 && (
                    <span className="text-xs text-gray-400 truncate" title={repo.sources.join(', ')}>
                      来源: {repo.sources[0].length > 40 ? repo.sources[0].substring(0, 40) + '...' : repo.sources[0]}
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="flex justify-end gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={onClose}
          >
            关闭
          </Button>
          <Button
            size="sm"
            onClick={onBatchAdd}
            disabled={selectedRepos.size === 0 || addingRepos}
          >
            {addingRepos ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Download className="w-4 h-4 mr-1" />}
            添加选中的 {selectedRepos.size} 个项目
          </Button>
        </div>
      </div>
    </motion.div>
  );
}
