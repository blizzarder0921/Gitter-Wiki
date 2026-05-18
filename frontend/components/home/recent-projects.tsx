'use client';

import { useMemo } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { ChevronDown, Clock, Search, X } from 'lucide-react';
import { InputGroup, InputGroupInput, InputGroupButton } from '@/components/ui/input-group';
import { type Project } from '@/lib/types';
import { ProjectCard } from './project-card';

/**
 * RecentProjectsProps - 最近项目区域入参
 *
 * @property projects - 所有项目列表
 * @property recentOpen - 最近项目区域是否展开
 * @property onRecentOpenChange - 展开/折叠切换回调
 * @property searchOpen - 搜索输入框是否展开
 * @property onSearchOpenChange - 搜索展开切换回调
 * @property searchQuery - 搜索关键字
 * @property onSearchQueryChange - 搜索文字变化回调
 * @property searchInputRef - 搜索输入框 ref
 * @property searchButtonRef - 搜索按钮 ref
 * @property onOpenDetail - 打开项目详情回调
 * @property fetchingResourcesId - 正在抓取资源的项目 ID
 * @property onRetryFetchResources - 重试抓取资源回调
 * @property onSetDetailProject - 设置当前详情项目
 * @property onOpenGraph - 打开知识图谱回调
 * @property onOpenFolder - 打开文件夹回调
 * @property onDelete - 删除项目回调
 * @property onPull - 拉取更新回调
 * @property pullingId - 正在拉取更新的项目 ID
 * @property onShareProject - 分享项目回调
 */
interface RecentProjectsProps {
  projects: Project[];
  recentOpen: boolean;
  onRecentOpenChange: (open: boolean) => void;
  searchOpen: boolean;
  onSearchOpenChange: (open: boolean) => void;
  searchQuery: string;
  onSearchQueryChange: (v: string) => void;
  searchInputRef: React.RefObject<HTMLInputElement | null>;
  searchButtonRef: React.RefObject<HTMLButtonElement | null>;
  onOpenDetail: (project: Project, e?: React.MouseEvent) => void;
  fetchingResourcesId: number | null;
  onRetryFetchResources: (project: Project) => void;
  onSetDetailProject: (project: Project) => void;
  onOpenGraph: (project: Project) => void;
  onOpenFolder: (path: string) => void;
  onDelete: (id: number) => void;
  onPull: (project: Project) => void;
  pullingId: number | null;
  onShare: (project: Project) => void;
}

/**
 * RecentProjects - 最近项目可折叠区域
 *
 * 展示最近项目列表，支持搜索过滤、折叠展开。
 * 搜索输入框支持动画展开/收起，过滤结果使用 ProjectCard 组件渲染。
 * 当没有任何项目时返回 null（不渲染）。
 */
export function RecentProjects({
  projects,
  recentOpen,
  onRecentOpenChange,
  searchOpen,
  onSearchOpenChange,
  searchQuery,
  onSearchQueryChange,
  searchInputRef,
  searchButtonRef,
  onOpenDetail,
  fetchingResourcesId,
  onRetryFetchResources,
  onSetDetailProject,
  onOpenGraph,
  onOpenFolder,
  onDelete,
  onPull,
  pullingId,
  onShare,
}: RecentProjectsProps) {
  // 根据搜索关键字过滤项目（大小写不敏感，匹配名称与描述）
  const filteredProjects = useMemo(() => {
    if (!searchQuery.trim()) return projects;
    const q = searchQuery.trim().toLowerCase();
    return projects.filter((p) => {
      const name = p.name?.toLowerCase() ?? '';
      const desc = p.description?.toLowerCase() ?? '';
      return name.includes(q) || desc.includes(q);
    });
  }, [projects, searchQuery]);

  // 无项目时不渲染
  if (projects.length === 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ delay: 0.5 }}
      className="relative z-10 mt-10 w-full max-w-6xl flex flex-col items-center"
    >
      {/* 折叠触发器 */}
      <div className="group w-full flex items-center gap-4 py-2">
        <div className="flex-1 h-px bg-border/40 group-hover:bg-border/70 transition-colors" />
        <div className="shrink-0 flex items-center gap-3 text-[13px] text-muted-foreground/60 select-none">
          <button
            onClick={() => onRecentOpenChange(!recentOpen)}
            className="flex items-center gap-2 hover:text-foreground/70 transition-colors cursor-pointer"
          >
            <Clock className="size-3.5" />
            最近项目
            <span className="text-[11px] tabular-nums opacity-60">{projects.length}</span>
            <motion.div animate={{ rotate: recentOpen ? 180 : 0 }} transition={{ duration: 0.3 }}>
              <ChevronDown className="size-3.5" />
            </motion.div>
          </button>

          {/* 搜索 */}
          <AnimatePresence initial={false}>
            {!searchOpen ? (
              <motion.button
                key="search-icon"
                ref={searchButtonRef}
                type="button"
                onClick={() => {
                  onSearchOpenChange(true);
                  if (!recentOpen) onRecentOpenChange(true);
                  requestAnimationFrame(() => searchInputRef.current?.focus());
                }}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.12 }}
                className="flex items-center justify-center size-6 rounded-full text-muted-foreground/50 hover:text-foreground/70 hover:bg-muted/50 transition-colors cursor-pointer"
              >
                <Search className="size-3.5" />
              </motion.button>
            ) : (
              <motion.div
                key="search-input"
                initial={{ opacity: 0, width: 0 }}
                animate={{ opacity: 1, width: 200 }}
                exit={{ opacity: 0, width: 0 }}
                transition={{ duration: 0.18 }}
                className="overflow-hidden"
              >
                <InputGroup className="h-7 text-[12px] rounded-full bg-muted/40 border-transparent shadow-none">
                  <InputGroupInput
                    ref={searchInputRef}
                    value={searchQuery}
                    onChange={(e) => onSearchQueryChange(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Escape') {
                        if (searchQuery) onSearchQueryChange('');
                        else onSearchOpenChange(false);
                      }
                    }}
                    onBlur={() => {
                      if (!searchQuery) onSearchOpenChange(false);
                    }}
                    placeholder="搜索项目..."
                    className="h-7 pl-3 placeholder:text-muted-foreground/50"
                  />
                  {searchQuery && (
                    <InputGroupButton
                      size="icon-xs"
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => {
                        onSearchQueryChange('');
                        searchInputRef.current?.focus();
                      }}
                    >
                      <X />
                    </InputGroupButton>
                  )}
                </InputGroup>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        <div className="flex-1 h-px bg-border/40 group-hover:bg-border/70 transition-colors" />
      </div>

      {/* 可折叠内容 */}
      <AnimatePresence>
        {recentOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.4 }}
            className="w-full overflow-hidden"
          >
            {searchQuery.trim() && filteredProjects.length === 0 ? (
              <div className="pt-8 pb-2 text-center text-[13px] text-muted-foreground/60">
                未找到匹配的项目
              </div>
            ) : (
              <div className="pt-8 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-x-5 gap-y-8">
                {filteredProjects.map((project, i) => (
                  <ProjectCard
                    key={project.id}
                    project={project}
                    index={i}
                    fetchingResourcesId={fetchingResourcesId}
                    pullingId={pullingId}
                    onOpenDetail={onOpenDetail}
                    onRetryFetchResources={onRetryFetchResources}
                    onSetDetailProject={onSetDetailProject}
                    onOpenGraph={onOpenGraph}
                    onOpenFolder={onOpenFolder}
                    onDelete={onDelete}
                    onPull={onPull}
                    onShare={onShare}
                  />
                ))}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
