'use client';

import { useState, useEffect, useRef } from 'react';
import { type Project } from '@/lib/types';
import { RECENT_OPEN_STORAGE_KEY } from '@/lib/types/home';
import { safeResJson } from '@/lib/utils/home';
import { createLogger } from '@/lib/logger';
import { toast } from 'sonner';

const log = createLogger('useProjects');

/**
 * 项目 CRUD 底层 Hook
 * 管理项目列表、列表面板、详情弹窗、分享、版本归档、删除确认等核心状态与操作
 * 不依赖任何外部 Hook
 */
export function useProjects() {
  /* ---- 状态定义 ---- */
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectListOpen, setProjectListOpen] = useState(false);
  const [projectSearch, setProjectSearch] = useState('');
  const [detailProject, setDetailProject] = useState<Project | null>(null);
  const [versionArchives, setVersionArchives] = useState<{ name: string; size: number; modifiedTime: string }[]>([]);
  const [loadingArchives, setLoadingArchives] = useState(false);
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null);
  const [recentOpen, setRecentOpen] = useState(true);
  const [fetchingResourcesId, setFetchingResourcesId] = useState<number | null>(null);
  const [shareOpen, setShareOpen] = useState(false);
  const [shareProject, setShareProject] = useState<Project | null>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);

  /* ---- 数据加载 ---- */

  /**
   * 加载项目列表
   */
  const loadProjects = async () => {
    try {
      const res = await fetch('/api/projects');
      if (res.ok) {
        const data = await res.json();
        setProjects(data);
      }
    } catch (err) {
      log.error('Failed to load projects:', err);
    }
  };

  /**
   * 加载项目版本归档列表
   * 直接调用 API，由后端根据 project.local_path 查询
   */
  const loadVersionArchives = async (projectId: number) => {
    setLoadingArchives(true);
    try {
      const res = await fetch(`/api/projects/${projectId}/archives`);
      if (res.ok) {
        const data = await res.json();
        setVersionArchives(data.archives || []);
      } else {
        setVersionArchives([]);
      }
    } catch {
      setVersionArchives([]);
    } finally {
      setLoadingArchives(false);
    }
  };

  /* ---- 删除操作 ---- */

  /**
   * 触发删除确认
   * @param id 待删除项目 ID
   */
  const handleDeleteProject = (id: number) => {
    setDeleteConfirmId(id);
  };

  /**
   * 执行删除项目
   * 删除后关闭面板，清理详情状态，延迟刷新列表
   */
  const confirmDeleteProject = async () => {
    const id = deleteConfirmId;
    if (!id) return;
    setDeleteConfirmId(null);
    try {
      const res = await fetch(`/api/projects/${id}`, { method: 'DELETE' });
      if (res.ok) {
        toast.success('删除成功');
        setProjectListOpen(false);
        if (detailProject?.id === id) {
          setDetailProject(null);
        }
        setTimeout(() => {
          loadProjects();
        }, 300);
      } else {
        const data = await safeResJson(res);
        toast.error(data.detail || '删除失败');
      }
    } catch (err) {
      log.error('Failed to delete project:', err);
      toast.error('删除失败');
    }
  };

  /* ---- 详情 & 操作 ---- */

  /**
   * 打开项目详情并加载版本归档
   * @param project 目标项目
   * @param e 可选鼠标事件，若点击源为 button/a 则忽略
   */
  const openProjectDetail = (project: Project, e?: React.MouseEvent) => {
    if (e) {
      const target = e.target as HTMLElement;
      if (target.closest('button') || target.closest('a')) return;
    }
    setDetailProject(project);
    loadVersionArchives(project.id);
  };

  /**
   * 重试抓取 GitHub 资源
   * 调用后端 API 重新抓取项目的 Issues、Releases 等
   */
  const handleRetryFetchResources = async (project: Project) => {
    setFetchingResourcesId(project.id);
    try {
      const res = await fetch(`/api/github/${project.id}/fetch-resources`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ priority: 'P0' }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.status === 'completed') {
          toast.success('资源抓取完成');
        } else if (data.status === 'partial') {
          toast.warning('部分资源抓取失败');
        } else {
          toast.error('资源抓取失败');
        }
        loadProjects();
      } else {
        const data = await safeResJson(res);
        toast.error(data.detail || '资源抓取失败');
      }
    } catch (err) {
      log.error('Failed to fetch resources:', err);
      toast.error('资源抓取失败');
    } finally {
      setFetchingResourcesId(null);
    }
  };

  /**
   * 打开本地文件夹
   * @param folderPath 要打开的文件夹路径
   */
  const handleOpenFolder = async (folderPath: string) => {
    try {
      const res = await fetch('/api/open-folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: folderPath }),
      });
      if (!res.ok) {
        const data = await safeResJson(res);
        toast.error(data.detail || '打开文件夹失败');
      }
    } catch {
      toast.error('打开文件夹失败');
    }
  };

  /**
   * 持久化最近项目面板展开状态
   * @param next 新的展开状态
   */
  const persistRecentOpen = (next: boolean) => {
    setRecentOpen(next);
    try {
      localStorage.setItem(RECENT_OPEN_STORAGE_KEY, String(next));
    } catch { /* localStorage 不可用时忽略 */ }
  };

  /* ---- 副作用 ---- */

  /** 挂载时加载项目列表 */
  useEffect(() => {
    loadProjects();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** 从 localStorage 恢复最近项目面板展开状态 */
  useEffect(() => {
    try {
      const saved = localStorage.getItem(RECENT_OPEN_STORAGE_KEY);
      if (saved !== null) setRecentOpen(saved !== 'false');
    } catch { /* localStorage 不可用时忽略 */ }
  }, []);

  /** 点击外部关闭项目列表面板 */
  useEffect(() => {
    if (!projectListOpen) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (toolbarRef.current && !toolbarRef.current.contains(e.target as Node)) {
        setProjectListOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [projectListOpen]);

  return {
    projects,
    loadProjects,
    projectListOpen,
    setProjectListOpen,
    projectSearch,
    setProjectSearch,
    detailProject,
    setDetailProject,
    versionArchives,
    loadingArchives,
    deleteConfirmId,
    setDeleteConfirmId,
    recentOpen,
    persistRecentOpen,
    fetchingResourcesId,
    shareOpen,
    setShareOpen,
    shareProject,
    setShareProject,
    toolbarRef,
    handleDeleteProject,
    confirmDeleteProject,
    openProjectDetail,
    handleRetryFetchResources,
    handleOpenFolder,
    loadVersionArchives,
  };
}
