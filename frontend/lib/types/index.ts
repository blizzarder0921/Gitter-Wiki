/**
 * Gitter 前端全局类型定义
 *
 * 集中管理项目相关的 TypeScript 接口，
 * 供 page.tsx、share-dialog.tsx 等组件共享使用。
 */

/** GitHub 资源抓取状态枚举 */
export type GithubFetchStatus = 'pending' | 'fetching' | 'completed' | 'partial' | 'failed';

/** 项目数据接口，与后端 projects 表字段一一对应 */
export interface Project {
  id: number;
  name: string;
  description: string | null;
  readme: string | null;
  github_url: string | null;
  local_path: string | null;
  version_type: string;
  latest_version: string | null;
  current_version: string | null;
  download_url: string | null;
  commit_sha: string | null;
  commit_date: string | null;
  sync_status: string;
  created_at: string;
  updated_at: string;
  last_synced_at: string | null;
  /** GitHub 资源抓取状态：pending/fetching/completed/partial/failed */
  github_fetch_status?: GithubFetchStatus;
  /** Issues 最后抓取时间（ISO 8601） */
  github_issues_fetched_at?: string | null;
  /** Releases 最后抓取时间（ISO 8601） */
  github_releases_fetched_at?: string | null;
  /** 工作流进度状态：idle/cleaning/cloning/building_graph/fetching_github/bridging/compiling_wiki/cleaning_up/done/failed */
  workflow_status?: string;
}
