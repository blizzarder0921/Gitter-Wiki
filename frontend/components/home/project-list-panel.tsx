'use client';

import { motion, AnimatePresence } from 'motion/react';
import { Search, RefreshCw, Loader2, FolderOpen } from 'lucide-react';
import { cn } from '@/lib/utils';
import { type Project } from '@/lib/types';
import { getSyncStatusInfo, getVersionTypeBadge, getFetchStatusInfo, getVersionDisplay, hasVersionUpdate } from '@/lib/utils/home';
import { ProjectActions } from './project-actions';

/**
 * ProjectListPanelProps - 右侧项目列表面板入参
 *
 * @property open - 面板是否展开
 * @property projects - 所有项目列表
 * @property projectSearch - 搜索关键字
 * @property onProjectSearchChange - 搜索变化回调
 * @property onUpdateAll - 一键更新回调
 * @property onOpenDetail - 打开项目详情回调（含事件对象，可选）
 * @property onClose - 关闭面板回调
 * @property fetchingResourcesId - 正在抓取资源的项目 ID
 * @property onRetryFetchResources - 重试抓取资源回调
 * @property onSetDetailProject - 设置详情项目
 * @property onOpenGraph - 打开知识图谱回调
 * @property onOpenFolder - 打开本地文件夹回调
 * @property onDeleteProject - 删除项目回调
 * @property onPullProject - 拉取更新回调
 * @property onShareProject - 分享项目回调
 * @property pullingId - 正在拉取更新的项目 ID
 */
interface ProjectListPanelProps {
  open: boolean;
  projects: Project[];
  projectSearch: string;
  onProjectSearchChange: (v: string) => void;
  onUpdateAll: () => void;
  onOpenDetail: (project: Project, e?: React.MouseEvent) => void;
  onClose: () => void;
  fetchingResourcesId: number | null;
  onRetryFetchResources: (project: Project) => void;
  onSetDetailProject: (project: Project) => void;
  onOpenGraph: (project: Project) => void;
  onOpenFolder: (path: string) => void;
  onDeleteProject: (id: number) => void;
  onPullProject: (project: Project) => void;
  onShareProject: (project: Project) => void;
  pullingId: number | null;
}

/**
 * ProjectListPanel - 右侧滑出项目列表面板
 *
 * 展示所有项目列表，支持搜索过滤、一键更新、查看详情、
 * 抓取资源、图谱、文件夹、Wiki 和分享等操作。
 */
export function ProjectListPanel({
  open,
  projects,
  projectSearch,
  onProjectSearchChange,
  onUpdateAll,
  onOpenDetail,
  onClose,
  fetchingResourcesId,
  onRetryFetchResources,
  onSetDetailProject,
  onOpenGraph,
  onOpenFolder,
  onDeleteProject,
  onPullProject,
  onShareProject,
  pullingId,
}: ProjectListPanelProps) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: 20 }}
          transition={{ duration: 0.2 }}
          className="fixed top-20 right-4 z-40 w-1/2 max-h-[calc(100dvh-8rem)] overflow-hidden bg-white/90 dark:bg-gray-800/90 backdrop-blur-xl rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl"
        >
          <div className="p-4 border-b border-gray-100 dark:border-gray-700 flex items-center justify-between gap-2">
            <h3 className="font-semibold text-sm">项目列表</h3>
            <button
              onClick={onUpdateAll}
              className="flex items-center gap-1.5 text-xs text-purple-600 dark:text-purple-400 hover:bg-purple-50 dark:hover:bg-purple-900/20 px-2 py-1 rounded-full transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              一键更新
            </button>
          </div>
          <div className="px-4 py-2 border-b border-gray-100 dark:border-gray-700">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
              <input
                type="text"
                value={projectSearch}
                onChange={(e) => onProjectSearchChange(e.target.value)}
                placeholder="搜索项目名称或描述..."
                className="w-full pl-8 pr-3 py-1.5 text-sm rounded-lg bg-gray-50 dark:bg-gray-700/50 border border-gray-200 dark:border-gray-600 focus:outline-none focus:ring-1 focus:ring-purple-400 focus:border-purple-400 transition-colors"
              />
            </div>
          </div>
          <div className="overflow-y-auto max-h-[calc(100dvh-15rem)]">
            {projects.length === 0 ? (
              <div className="p-8 text-center text-sm text-gray-400">暂无项目</div>
            ) : (
              <div className="p-2 space-y-2">
                {projects
                  .filter((p) => {
                    if (!projectSearch.trim()) return true;
                    const q = projectSearch.toLowerCase();
                    return (
                      p.name.toLowerCase().includes(q) ||
                      (p.description && p.description.toLowerCase().includes(q)) ||
                      (p.github_url && p.github_url.toLowerCase().includes(q))
                    );
                  })
                  .map((project) => {
                  const status = getSyncStatusInfo(project);
                  const versionBadge = getVersionTypeBadge(project.version_type);
                  const fetchInfo = project.github_url ? getFetchStatusInfo(project.github_fetch_status) : null;
                  const canRetry = project.github_url && (project.github_fetch_status === 'partial' || project.github_fetch_status === 'failed');
                  return (
                    <div
                      key={project.id}
                      className="p-3 rounded-xl bg-gray-50 dark:bg-gray-700/50 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors cursor-pointer"
                      onClick={(e) => { onOpenDetail(project, e); onClose(); }}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-sm truncate">{project.name}</span>
                            <span className="flex items-center gap-1 text-xs text-gray-400">
                              <versionBadge.icon className={cn('w-3 h-3', versionBadge.color)} />
                              {project.current_version || getVersionDisplay(project)}
                              {hasVersionUpdate(project) && project.latest_version && (
                                <span className="text-yellow-500">
                                  → {project.latest_version}
                                </span>
                              )}
                            </span>
                          </div>
                          <p className="text-xs text-gray-500 dark:text-gray-400 truncate mt-0.5">
                            {project.description || '无描述'}
                          </p>
                          <div className="flex items-center gap-2 mt-1">
                            {fetchInfo && (
                              <span className={cn('flex items-center gap-1 text-xs px-1.5 py-0.5 rounded-full', fetchInfo.bg, fetchInfo.color)}>
                                {project.github_fetch_status === 'fetching' ? (
                                  <Loader2 className="w-3 h-3 animate-spin" />
                                ) : (
                                  <span className={cn('w-1.5 h-1.5 rounded-full', fetchInfo.dotColor)} />
                                )}
                                {fetchInfo.text}
                              </span>
                            )}
                            <span className={cn('flex items-center gap-1 text-xs px-1.5 py-0.5 rounded-full', status.bg, status.color)}>
                              <status.icon className="w-3 h-3" />
                              {status.text}
                            </span>
                            {project.local_path && (
                              <span className="text-xs text-gray-400 truncate">
                                <FolderOpen className="w-3 h-3 inline mr-0.5" />
                                {project.local_path}
                              </span>
                            )}
                          </div>
                        </div>
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
                          <ProjectActions
                            project={project}
                            pullingId={pullingId}
                            onOpenFolder={(path) => onOpenFolder(path)}
                            onOpenGraph={(p, e) => { e.preventDefault(); e.stopPropagation(); onSetDetailProject(p); onOpenGraph(p); }}
                            onPull={(p, e) => { e.preventDefault(); e.stopPropagation(); onPullProject(p); }}
                            onShare={(p, e) => { e.preventDefault(); e.stopPropagation(); onShareProject(p); }}
                            onDelete={(id, e) => { e.preventDefault(); e.stopPropagation(); onDeleteProject(id); }}
                            onSetDetailProject={onSetDetailProject}
                          />
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
