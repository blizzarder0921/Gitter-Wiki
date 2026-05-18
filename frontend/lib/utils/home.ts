'use client';

import { type Project, type GithubFetchStatus } from '@/lib/types';
import {
  Package,
  Tag,
  Calendar,
  AlertCircle,
  Check,
  X,
} from 'lucide-react';

/**
 * 安全解析响应 JSON，后端返回纯文本时不会抛异常
 */
export async function safeResJson<T = { detail?: string }>(res: Response): Promise<T & { detail?: string }> {
  try {
    return await res.json();
  } catch {
    const text = await res.text().catch(() => '');
    return { detail: text || `HTTP ${res.status}` } as T & { detail?: string };
  }
}

/**
 * 获取版本类型的图标和标签
 */
export function getVersionTypeBadge(versionType: string) {
  switch (versionType) {
    case 'release':
      return { icon: Package, label: 'Release', color: 'text-blue-500' };
    case 'tag':
      return { icon: Tag, label: 'Tag', color: 'text-purple-500' };
    case 'commit':
      return { icon: Calendar, label: 'Commit', color: 'text-orange-500' };
    default:
      return { icon: AlertCircle, label: '未知', color: 'text-gray-400' };
  }
}

/**
 * 获取同步状态的图标和标签
 */
export function getSyncStatusInfo(project: Project) {
  switch (project.sync_status) {
    case 'synced':
      return { icon: Check, color: 'text-green-500', text: '已同步', bg: 'bg-green-50 dark:bg-green-900/20' };
    case 'updatable':
      return { icon: AlertCircle, color: 'text-yellow-500', text: '可更新', bg: 'bg-yellow-50 dark:bg-yellow-900/20' };
    case 'failed':
      return { icon: X, color: 'text-red-500', text: '更新失败', bg: 'bg-red-50 dark:bg-red-900/20' };
    default:
      return { icon: AlertCircle, color: 'text-gray-400', text: '未同步', bg: 'bg-gray-50 dark:bg-gray-900/20' };
  }
}

/**
 * 获取 GitHub 资源抓取状态的显示信息
 * 根据不同状态返回颜色、文本和图标样式
 */
export function getFetchStatusInfo(status?: GithubFetchStatus) {
  switch (status) {
    case 'completed':
      return { color: 'text-green-500', bg: 'bg-green-50 dark:bg-green-900/20', text: '资源已同步', dotColor: 'bg-green-500' };
    case 'partial':
      return { color: 'text-yellow-500', bg: 'bg-yellow-50 dark:bg-yellow-900/20', text: '部分资源缺失', dotColor: 'bg-yellow-500' };
    case 'failed':
      return { color: 'text-red-500', bg: 'bg-red-50 dark:bg-red-900/20', text: '资源获取失败', dotColor: 'bg-red-500' };
    case 'fetching':
      return { color: 'text-blue-500', bg: 'bg-blue-50 dark:bg-blue-900/20', text: '正在获取...', dotColor: 'bg-blue-500' };
    case 'pending':
    default:
      return { color: 'text-gray-400', bg: 'bg-gray-50 dark:bg-gray-900/20', text: '待获取', dotColor: 'bg-gray-400' };
  }
}

/**
 * 获取版本号的显示文本
 * 优先显示 current_version（本地版本），若无则显示 latest_version
 */
export function getVersionDisplay(project: Project) {
  const version = project.current_version || project.latest_version;
  if (project.version_type === 'release' || project.version_type === 'tag') {
    return version || '未知';
  }
  if (project.commit_date) {
    return new Date(project.commit_date).toLocaleDateString();
  }
  return '-';
}

/**
 * 判断项目是否有版本更新（当前版本与最新版本不一致）
 */
export function hasVersionUpdate(project: Project): boolean {
  if (project.sync_status === 'updatable') return true;
  if (!project.current_version || !project.latest_version) return false;
  return project.current_version !== project.latest_version;
}
