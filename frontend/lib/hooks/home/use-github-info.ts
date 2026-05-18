'use client';

import { useState } from 'react';
import type { GithubInfo } from '@/lib/types/home';
import { createLogger } from '@/lib/logger';
import { toast } from 'sonner';

/**
 * useGithubInfo Hook
 *
 * 管理 GitHub 项目信息获取流程：loading 状态、预览数据、以及请求函数。
 *
 * @param form 包含 githubUrl 的表单状态对象，handleFetchGithubInfo 会读取其 githubUrl 发起请求
 * @returns { loading, previewInfo, setPreviewInfo, handleFetchGithubInfo }
 */
export function useGithubInfo(form: { githubUrl: string }) {
  const log = createLogger('GithubInfo');
  const [loading, setLoading] = useState(false);
  const [previewInfo, setPreviewInfo] = useState<GithubInfo | null>(null);

  /**
   * 获取 GitHub 项目信息
   * 调用后端 /api/github-info 接口，根据 URL 获取项目的名称、描述、README 等预览数据
   */
  const handleFetchGithubInfo = async () => {
    if (!form.githubUrl.trim()) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/github-info?url=${encodeURIComponent(form.githubUrl)}`);
      const data = await res.json();
      if (res.ok) {
        setPreviewInfo(data);
      } else {
        toast.error(data.detail || '获取项目信息失败');
      }
    } catch (err) {
      log.error('Failed to fetch github info:', err);
      toast.error('获取项目信息失败');
    } finally {
      setLoading(false);
    }
  };

  return { loading, previewInfo, setPreviewInfo, handleFetchGithubInfo };
}
