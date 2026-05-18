'use client';

import { motion } from 'motion/react';
import {
  Package,
  Loader2,
  Network,
  FolderOpen,
  RefreshCw,
  Trash2,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { type Project } from '@/lib/types';
import {
  getSyncStatusInfo,
  getVersionTypeBadge,
  getFetchStatusInfo,
  getVersionDisplay,
  hasVersionUpdate,
} from '@/lib/utils/home';

/**
 * ProjectCardProps - 项目卡片组件入参
 *
 * @property project - 目标项目数据
 * @property index - 在网格中的索引，用于进场动画延迟
 * @property onOpenDetail - 点击卡片打开项目详情回调
 * @property pullingId - 正在执行拉取更新的项目 ID
 * @property fetchingResourcesId - 正在抓取 GitHub 资源的项目 ID
 * @property onOpenFolder - 打开本地文件夹回调
 * @property onOpenGraph - 打开知识图谱回调
 * @property onPull - 拉取更新回调
 * @property onShare - 分享回调
 * @property onDelete - 删除回调
 * @property onSetDetailProject - 设置当前详情项目
 * @property onRetryFetchResources - 重试抓取 GitHub 资源回调
 */
interface ProjectCardProps {
  project: Project;
  index: number;
  onOpenDetail: (project: Project, e?: React.MouseEvent) => void;
  pullingId: number | null;
  fetchingResourcesId: number | null;
  onOpenFolder: (path: string) => void;
  onOpenGraph: (project: Project) => void;
  onPull: (project: Project) => void;
  onShare: (project: Project) => void;
  onDelete: (id: number) => void;
  onSetDetailProject: (project: Project) => void;
  onRetryFetchResources: (project: Project) => void;
}

/**
 * ProjectCard - 最近项目网格中的单个项目卡片
 *
 * 展示项目名称、描述、版本信息、同步/GitHub 抓取状态徽章，
 * 以及知识图谱、打开文件夹、Wiki、删除等操作按钮。
 * 支持 motion 进场动画，索引用于计算延迟。
 */
export function ProjectCard({
  project,
  index,
  onOpenDetail,
  pullingId,
  fetchingResourcesId,
  onOpenFolder,
  onOpenGraph,
  onPull,
  onShare,
  onDelete,
  onSetDetailProject,
  onRetryFetchResources,
}: ProjectCardProps) {
  const status = getSyncStatusInfo(project);
  const versionBadge = getVersionTypeBadge(project.version_type);
  const fetchInfo = project.github_url ? getFetchStatusInfo(project.github_fetch_status) : null;
  const canRetry = project.github_url && (project.github_fetch_status === 'partial' || project.github_fetch_status === 'failed');

  return (
    <motion.div
      key={project.id}
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.9 }}
      transition={{ delay: index * 0.04, duration: 0.35 }}
      layout
      className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-100 dark:border-gray-700 p-4 hover:shadow-lg transition-shadow cursor-pointer"
      onClick={(e) => onOpenDetail(project, e)}
    >
      <div className="flex items-start justify-between gap-2 mb-3">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500/20 to-blue-500/20 flex items-center justify-center">
          <Package className="w-5 h-5 text-purple-600 dark:text-purple-400" />
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {fetchInfo && (
            <span className={cn('inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full', fetchInfo.bg, fetchInfo.color)}>
              {project.github_fetch_status === 'fetching' ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <span className={cn('w-1.5 h-1.5 rounded-full', fetchInfo.dotColor)} />
              )}
              {fetchInfo.text}
            </span>
          )}
          <span className={cn('inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full shrink-0', status.bg, status.color)}>
            <status.icon className="w-3 h-3" />
            {status.text}
          </span>
        </div>
      </div>
      <h4 className="font-semibold text-sm mb-1 truncate">{project.name}</h4>
      <p className="text-xs text-gray-500 dark:text-gray-400 line-clamp-2 mb-3 min-h-[2rem]">
        {project.description || '无描述'}
      </p>
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1 text-xs font-mono text-gray-400">
          <versionBadge.icon className={cn('w-3 h-3', versionBadge.color)} />
          {project.current_version || getVersionDisplay(project)}
          {hasVersionUpdate(project) && project.latest_version && (
            <span className="text-yellow-500">
              → {project.latest_version}
            </span>
          )}
        </span>
        <div className="flex items-center gap-1">
          {canRetry && (
            <button
              type="button"
              title="重试抓取资源"
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); onRetryFetchResources(project); }}
              disabled={fetchingResourcesId === project.id}
              className="p-1.5 rounded-lg text-gray-400 hover:text-orange-500 hover:bg-orange-50 dark:hover:bg-orange-900/20 transition-colors disabled:opacity-50 relative z-10"
            >
              {fetchingResourcesId === project.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            </button>
          )}
          {project.local_path && (
            <>
              <button
                type="button"
                title="知识图谱"
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); onSetDetailProject(project); onOpenGraph(project); }}
                className="p-1.5 rounded-lg text-gray-400 hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors relative z-10"
              >
                <Network className="w-4 h-4" />
              </button>
              <button
                type="button"
                title="打开文件夹"
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); onOpenFolder(project.local_path!); }}
                className="p-1.5 rounded-lg text-gray-400 hover:text-green-500 transition-colors relative z-10"
              >
                <FolderOpen className="w-4 h-4" />
              </button>
            </>
          )}
          <button
            type="button"
            title="删除"
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); onDelete(project.id); }}
            className="p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors relative z-10"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>
    </motion.div>
  );
}
