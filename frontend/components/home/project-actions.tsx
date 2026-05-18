'use client';

import {
  FolderOpen,
  Network,
  RefreshCw,
  Loader2,
  Share2,
  Trash2,
} from 'lucide-react';
import { type Project } from '@/lib/types';

/**
 * ProjectActionsProps - 项目操作按钮组组件入参
 *
 * @property project - 目标项目
 * @property size - 按钮尺寸（sm: 较大内边距, xs: 紧凑内边距）
 * @property pullingId - 正在执行拉取更新的项目 ID，用于禁用按钮和显示加载动画
 * @property onOpenFolder - 打开本地文件夹回调
 * @property onOpenGraph - 打开知识图谱回调（含事件对象）
 * @property onPull - 拉取更新回调（含事件对象）
 * @property onShare - 分享回调（含事件对象）
 * @property onDelete - 删除回调（含事件对象）
 * @property onSetDetailProject - 设置当前详情项目
 */
interface ProjectActionsProps {
  project: Project;
  size?: 'sm' | 'xs';
  pullingId: number | null;
  onOpenFolder: (path: string) => void;
  onOpenGraph: (project: Project, e: React.MouseEvent) => void;
  onPull: (project: Project, e: React.MouseEvent) => void;
  onShare: (project: Project, e: React.MouseEvent) => void;
  onDelete: (id: number, e: React.MouseEvent) => void;
  onSetDetailProject: (project: Project) => void;
}

/**
 * ProjectActions - 项目操作按钮组
 *
 * 展示项目的操作按钮：打开文件夹、知识图谱、Wiki、更新、分享、删除。
 * 每个按钮内部处理事件冒泡阻止，适用于卡片和列表两种展示场景。
 */
export function ProjectActions({
  project,
  size = 'xs',
  pullingId,
  onOpenFolder,
  onOpenGraph,
  onPull,
  onShare,
  onDelete,
  onSetDetailProject,
}: ProjectActionsProps) {
  const iconSize = size === 'sm' ? 'w-4 h-4' : 'w-4 h-4';
  const padding = size === 'sm' ? 'p-2.5' : 'p-2';

  return (
    <>
      {project.local_path ? (
        <>
          {/* 打开文件夹 */}
          <button
            type="button"
            title="打开文件夹"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onOpenFolder(project.local_path!);
            }}
            className={`${padding} rounded-lg text-gray-400 hover:text-green-500 hover:bg-green-50 dark:hover:bg-green-900/20 transition-colors relative z-10`}
          >
            <FolderOpen className={iconSize} />
          </button>

          {/* 知识图谱 */}
          <button
            type="button"
            title="知识图谱"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onSetDetailProject(project);
              onOpenGraph(project, e);
            }}
            className={`${padding} rounded-lg text-gray-400 hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors relative z-10`}
          >
            <Network className={iconSize} />
          </button>

          {/* 更新按钮（仅可更新状态展示） */}
          {project.sync_status === 'updatable' && (
            <button
              type="button"
              title="更新"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                onPull(project, e);
              }}
              disabled={pullingId === project.id}
              className={`${padding} rounded-lg text-gray-400 hover:text-yellow-500 hover:bg-yellow-50 dark:hover:bg-yellow-900/20 transition-colors disabled:opacity-50 relative z-10`}
            >
              {pullingId === project.id ? (
                <Loader2 className={`${iconSize} animate-spin`} />
              ) : (
                <RefreshCw className={iconSize} />
              )}
            </button>
          )}
        </>
      ) : null}

      {/* 分享按钮 */}
      <button
        type="button"
        title="分享"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          onShare(project, e);
        }}
        className={`${padding} rounded-lg text-gray-400 hover:text-purple-500 hover:bg-purple-50 dark:hover:bg-purple-900/20 transition-colors relative z-10`}
      >
        <Share2 className={iconSize} />
      </button>

      {/* 删除按钮 */}
      <button
        type="button"
        title="删除"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          onDelete(project.id, e);
        }}
        className={`${padding} rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors relative z-10`}
      >
        <Trash2 className={iconSize} />
      </button>
    </>
  );
}
