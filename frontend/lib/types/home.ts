'use client';

import { type Project, type GithubFetchStatus } from '@/lib/types';

/**
 * GitHub 项目预览信息（获取信息接口返回）
 */
export interface GithubInfo {
  name: string;
  description: string;
  githubUrl: string;
  versionType: string;
  latestVersion: string | null;
  downloadUrl: string | null;
  commitSha: string | null;
  commitDate: string | null;
  readme: string | null;
}

/**
 * 压缩包解析结果
 */
export interface ExtractResult {
  success: boolean;
  githubUrl: string | null;
  name: string;
  description: string | null;
  readme: string | null;
  versionType: string;
  versionInfo: string | null;
  commitSha: string | null;
  commitDate: string | null;
  latestVersion: string | null;
  downloadUrl: string | null;
  tempId: string;
  duplicate: {
    exists: boolean;
    existingProject: Project | null;
    versionComparison: 'same' | 'newer' | 'older' | 'unknown' | null;
  };
  error?: string;
}

/**
 * 批量提取结果
 */
export interface BatchExtractResult {
  total: number;
  success: number;
  failed: number;
  results: Array<{
    input: string;
    type: string;
    githubUrls: string[];
    status: string;
    error?: string;
  }>;
  repos: Array<{
    url: string;
    name: string;
    description: string | null;
    existsInDb: boolean;
    existingProjectId?: number;
    sources: string[];
  }>;
}

/**
 * 仓库添加状态
 */
export type RepoAddStatus = 'pending' | 'adding' | 'success' | 'failed';

/**
 * localstorage 键名：最近项目展开状态
 */
export const RECENT_OPEN_STORAGE_KEY = 'recentProjectsOpen';

/**
 * 工作流步骤标签映射
 */
export const WORKFLOW_LABELS: Record<string, string> = {
  idle: "空闲",
  cleaning: "清理旧文件",
  cloning: "正在下载代码",
  building_graph: "构建知识图谱",
  fetching_github: "抓取 GitHub 资源",
  bridging: "桥接知识库",
  compiling_wiki: "编译 Wiki 页面",
  cleaning_up: "清理临时文件",
  done: "完成",
  failed: "失败",
};

/**
 * 表单初始状态
 */
export const initialFormState = {
  githubUrl: '',
};
