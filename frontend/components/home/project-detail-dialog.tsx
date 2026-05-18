'use client';

/**
 * 项目详情弹窗组件
 * 展示项目的详细信息：版本、同步状态、操作按钮、版本归档、README 等
 */
import {
  Package,
  ExternalLink,
  FolderOpen,
  Loader2,
  RefreshCw,
  AlertCircle,
  Download,
  Languages,
  ChevronDown,
  Network,
  Share2,
  FileArchive,
  Archive,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { rehypeStripReactIgnoredAttrs } from '@/lib/utils/rehype-strip-attrs';
import { rewriteReadmeImagePaths } from '@/lib/utils/readme';
import { cn } from '@/lib/utils';
import { type Project } from '@/lib/types';
import {
  getVersionTypeBadge,
  getSyncStatusInfo,
  getFetchStatusInfo,
  getVersionDisplay,
  hasVersionUpdate,
} from '@/lib/utils/home';

export interface ProjectDetailDialogProps {
  project: Project | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  versionArchives: Array<{ name: string; size: number; modifiedTime: string }>;
  loadingArchives: boolean;
  cloningId: number | null;
  pullingId: number | null;
  translatingId: number | null;
  fetchingResourcesId: number | null;
  onClone: (project: Project) => void;
  onPull: (project: Project) => void;
  onTranslate: (project: Project, targetLang: 'zh' | 'en') => void;
  onOpenGraph: (project: Project) => void;
  onOpenFolder: (path: string) => void;
  onRetryFetchResources: (project: Project) => void;
  onShare: (project: Project) => void;
  onSetDetailProject: (project: Project | null) => void;
}

/**
 * 项目详情弹窗
 * 展示项目完整信息，包括版本、同步状态、操作按钮、README 等
 */
export function ProjectDetailDialog({
  project,
  open,
  onOpenChange,
  versionArchives,
  loadingArchives,
  cloningId,
  pullingId,
  translatingId,
  fetchingResourcesId,
  onClone,
  onPull,
  onTranslate,
  onOpenGraph,
  onOpenFolder,
  onRetryFetchResources,
  onShare,
  onSetDetailProject,
}: ProjectDetailDialogProps) {
  const handleOpenChange = (value: boolean) => {
    onOpenChange(value);
    if (!value) {
      onSetDetailProject(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-5xl w-[95vw] max-h-[90vh] overflow-hidden flex flex-col p-0">
        {project && (
          <>
            {/* 头部 */}
            <DialogHeader className="px-6 pt-6 pb-4 border-b shrink-0">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-purple-500/20 to-blue-500/20 flex items-center justify-center">
                  <Package className="w-6 h-6 text-purple-600 dark:text-purple-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <DialogTitle className="text-xl">{project.name}</DialogTitle>
                  <DialogDescription className="text-sm mt-1 line-clamp-2">
                    {project.description || '无描述'}
                  </DialogDescription>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {project.github_url && (() => {
                    const fetchInfo = getFetchStatusInfo(project.github_fetch_status);
                    return (
                      <span className={cn('inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full', fetchInfo.bg, fetchInfo.color)}>
                        {project.github_fetch_status === 'fetching' ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <span className={cn('w-1.5 h-1.5 rounded-full', fetchInfo.dotColor)} />
                        )}
                        {fetchInfo.text}
                      </span>
                    );
                  })()}
                  {(() => {
                    const status = getSyncStatusInfo(project);
                    return (
                      <span className={cn('inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full', status.bg, status.color)}>
                        <status.icon className="w-3.5 h-3.5" />
                        {status.text}
                      </span>
                    );
                  })()}
                </div>
              </div>
            </DialogHeader>

            {/* 内容区 - 可滚动 */}
            <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
              {/* 链接信息 */}
              <div className={cn("grid gap-4", project.github_url ? "grid-cols-2" : "grid-cols-1")}>
                {project.github_url && (
                <div className="p-4 rounded-xl bg-gray-50 dark:bg-gray-800/60">
                  <div className="text-xs text-gray-400 mb-2 font-medium">GitHub 地址</div>
                  <div className="flex items-center gap-2">
                    <a
                      href={project.github_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm text-blue-500 hover:underline truncate flex-1"
                    >
                      {project.github_url}
                    </a>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => window.open(project.github_url!, '_blank')}
                      className="shrink-0 h-7 w-7 p-0"
                    >
                      <ExternalLink className="w-3.5 h-3.5" />
                    </Button>
                  </div>
                </div>
                )}
                {!project.github_url && (
                <div className="p-4 rounded-xl bg-amber-50 dark:bg-amber-900/20">
                  <div className="text-xs text-amber-500 mb-2 font-medium">项目类型</div>
                  <div className="flex items-center gap-2 text-sm text-amber-700 dark:text-amber-300">
                    <FolderOpen className="w-4 h-4" />
                    本地项目（无 GitHub 关联，不支持在线更新）
                  </div>
                </div>
                )}
                <div className="p-4 rounded-xl bg-gray-50 dark:bg-gray-800/60">
                  <div className="text-xs text-gray-400 mb-2 font-medium">本地路径</div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm truncate flex-1 font-mono">
                      {project.local_path || '未设置'}
                    </span>
                    {project.local_path && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => onOpenFolder(project.local_path!)}
                        className="shrink-0 h-7 w-7 p-0"
                      >
                        <FolderOpen className="w-3.5 h-3.5" />
                      </Button>
                    )}
                  </div>
                </div>
              </div>

              {/* GitHub 资源抓取状态 */}
              {project.github_url && (() => {
                const fetchInfo = getFetchStatusInfo(project.github_fetch_status);
                const canRetry = project.github_fetch_status === 'partial' || project.github_fetch_status === 'failed';
                return (
                  <div className={cn('flex items-center gap-3 p-3 rounded-xl border', fetchInfo.bg, 'border-current/10')}>
                    {project.github_fetch_status === 'fetching' ? (
                      <Loader2 className={cn('w-4 h-4 shrink-0 animate-spin', fetchInfo.color)} />
                    ) : (
                      <span className={cn('w-2 h-2 rounded-full shrink-0', fetchInfo.dotColor)} />
                    )}
                    <span className={cn('text-sm', fetchInfo.color)}>{fetchInfo.text}</span>
                    {project.github_issues_fetched_at && (
                      <span className="text-xs text-gray-400 ml-auto">
                        Issues: {new Date(project.github_issues_fetched_at).toLocaleDateString()}
                      </span>
                    )}
                    {project.github_releases_fetched_at && (
                      <span className="text-xs text-gray-400">
                        Releases: {new Date(project.github_releases_fetched_at).toLocaleDateString()}
                      </span>
                    )}
                    {canRetry && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => onRetryFetchResources(project)}
                        disabled={fetchingResourcesId === project.id}
                        className="ml-auto shrink-0 h-7 text-xs"
                      >
                        {fetchingResourcesId === project.id ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : <RefreshCw className="w-3.5 h-3.5 mr-1" />}
                        重试抓取
                      </Button>
                    )}
                  </div>
                );
              })()}

              {/* 版本信息 */}
              <div className="grid grid-cols-4 gap-4">
                <div className="p-4 rounded-xl bg-gray-50 dark:bg-gray-800/60">
                  <div className="text-xs text-gray-400 mb-2">版本类型</div>
                  <div className="flex items-center gap-1.5">
                    {(() => {
                      const badge = getVersionTypeBadge(project.version_type);
                      return <><badge.icon className={cn('w-4 h-4', badge.color)} /><span className="text-sm font-medium">{badge.label}</span></>;
                    })()}
                  </div>
                </div>
                <div className="p-4 rounded-xl bg-gray-50 dark:bg-gray-800/60">
                  <div className="text-xs text-gray-400 mb-2">当前版本</div>
                  <span className="text-sm font-mono">
                    {project.current_version || getVersionDisplay(project)}
                  </span>
                </div>
                <div className="p-4 rounded-xl bg-gray-50 dark:bg-gray-800/60">
                  <div className="text-xs text-gray-400 mb-2">最新版本</div>
                  <span className={cn(
                    'text-sm font-mono',
                    hasVersionUpdate(project) && project.latest_version
                      ? 'text-yellow-600 dark:text-yellow-400 font-semibold'
                      : '',
                  )}>
                    {project.latest_version || '-'}
                  </span>
                </div>
                <div className="p-4 rounded-xl bg-gray-50 dark:bg-gray-800/60">
                  <div className="text-xs text-gray-400 mb-2">最后同步</div>
                  <span className="text-sm">
                    {project.last_synced_at
                      ? new Date(project.last_synced_at).toLocaleString()
                      : '从未同步'}
                  </span>
                </div>
              </div>

              {/* 版本更新提示 */}
              {hasVersionUpdate(project) && project.latest_version && (
                <div className="flex items-center gap-2 p-3 rounded-xl bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800">
                  <AlertCircle className="w-4 h-4 text-yellow-500 shrink-0" />
                  <span className="text-sm text-yellow-700 dark:text-yellow-300">
                    有新版本可用：{project.current_version || '未知'} → {project.latest_version}
                  </span>
                  {project.local_path && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => onPull(project)}
                      disabled={pullingId === project.id}
                      className="ml-auto shrink-0 h-7 text-xs"
                    >
                      {pullingId === project.id ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : <RefreshCw className="w-3.5 h-3.5 mr-1" />}
                      更新项目
                    </Button>
                  )}
                </div>
              )}

              {/* 操作按钮 */}
              <div className="flex flex-wrap gap-2">
                {!project.local_path && (
                  <Button
                    size="sm"
                    className="!text-white"
                    onClick={() => onClone(project)}
                    disabled={cloningId === project.id}
                  >
                    {cloningId === project.id ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Download className="w-4 h-4 mr-1" />}
                    克隆到本地
                  </Button>
                )}
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={translatingId === project.id}
                    >
                      {translatingId === project.id ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Languages className="w-4 h-4 mr-1" />}
                      翻译
                      <ChevronDown className="w-3 h-3 ml-1 opacity-50" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start" className="w-40">
                    <DropdownMenuItem onClick={() => onTranslate(project, 'zh')}>
                      <Languages className="w-4 h-4 mr-2" />
                      翻译成中文
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => onTranslate(project, 'en')}>
                      <Languages className="w-4 h-4 mr-2" />
                      翻译成英文
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
                
                {project.local_path && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => onOpenGraph(project)}
                  >
                    <Network className="w-4 h-4 mr-1" />
                    知识图谱
                  </Button>
                )}
                {project.github_url && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onPull(project)}
                  disabled={pullingId === project.id}
                >
                  {pullingId === project.id ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <RefreshCw className="w-4 h-4 mr-1" />}
                  更新项目
                </Button>
                )}
                {/* 分享按钮 */}
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onShare(project)}
                >
                  <Share2 className="w-4 h-4 mr-1" />
                  分享
                </Button>
              </div>

              {/* 版本归档 */}
              {project.local_path && (
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <h4 className="text-sm font-semibold flex items-center gap-2">
                      <Archive className="w-4 h-4 text-purple-500" />
                      版本归档
                    </h4>
                    <span className="text-xs text-gray-400">
                      {versionArchives.length > 0 ? `${versionArchives.length} 个版本` : '暂无归档'}
                    </span>
                  </div>
                  {loadingArchives ? (
                    <div className="flex items-center justify-center py-6">
                      <Loader2 className="w-5 h-5 text-gray-400 animate-spin" />
                    </div>
                  ) : versionArchives.length > 0 ? (
                    <div className="space-y-2">
                      {versionArchives.map((archive) => (
                        <div
                          key={archive.name}
                          className="flex items-center justify-between p-3 rounded-xl bg-gray-50 dark:bg-gray-800/60 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                        >
                          <div className="flex items-center gap-2 min-w-0 flex-1">
                            <FileArchive className="w-4 h-4 text-purple-400 shrink-0" />
                            <span className="text-sm font-mono truncate">{archive.name}</span>
                          </div>
                          <div className="flex items-center gap-3 shrink-0 ml-3">
                            <span className="text-xs text-gray-400">
                              {(archive.size / 1024 / 1024).toFixed(2)} MB
                            </span>
                            <span className="text-xs text-gray-400">
                              {new Date(archive.modifiedTime).toLocaleDateString()}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-center py-6 text-sm text-gray-400">
                      克隆或上传项目后，版本压缩包将自动保存在此
                    </div>
                  )}
                  {project.local_path && (
                    <p className="text-xs text-gray-400 mt-2">
                      存储路径：{project.local_path}
                    </p>
                  )}
                </div>
              )}

              {/* README */}
              {project.readme && (
                <div>
                  <h4 className="text-sm font-semibold mb-3">README</h4>
                  <div className="prose prose-sm dark:prose-invert max-w-none p-5 rounded-xl bg-gray-50 dark:bg-gray-800/60">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw, rehypeStripReactIgnoredAttrs]}>
                      {rewriteReadmeImagePaths(project.readme, project.github_url)}
                    </ReactMarkdown>
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
