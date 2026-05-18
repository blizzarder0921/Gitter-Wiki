'use client';

import { useState, useRef } from 'react';
import type { ExtractResult, BatchExtractResult, RepoAddStatus, GithubInfo } from '@/lib/types/home';
import { initialFormState } from '@/lib/types/home';
import { createLogger } from '@/lib/logger';
import { toast } from 'sonner';
import { safeResJson } from '@/lib/utils/home';
import { useSettingsStore } from '@/lib/store/settings';

const log = createLogger('Extract');

/**
 * 压缩包上传/解析 与 批量提取 Hook
 *
 * 管理 zip 上传解析、批量提取、批量添加等流程
 *
 * @param deps 外部依赖：loadProjects / form / setForm / setPreviewInfo / addingProject / setAddingProject
 * @returns 状态与方法集合
 */
export function useExtract(deps: {
  loadProjects: () => Promise<void>;
  form: { githubUrl: string };
  setForm: (form: { githubUrl: string }) => void;
  setPreviewInfo: (info: GithubInfo | null) => void;
  addingProject: boolean;
  setAddingProject: (v: boolean) => void;
}) {
  const { loadProjects, form, setForm, setPreviewInfo, addingProject, setAddingProject } = deps;

  /* ---- 全局设置（在 hook 内部读取，避免 page.tsx 冗余读取） ---- */
  const localStoragePath = useSettingsStore((state) => state.localStoragePath);
  const archiveFormat = useSettingsStore((state) => state.archiveFormat);
  const providerId = useSettingsStore((state) => state.providerId);
  const modelId = useSettingsStore((state) => state.modelId);
  const providersConfig = useSettingsStore((state) => state.providersConfig);

  /* ---- 状态定义 ---- */
  const [uploading, setUploading] = useState(false);
  const [extractResult, setExtractResult] = useState<ExtractResult | null>(null);
  const [showOverwriteConfirm, setShowOverwriteConfirm] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [extractResults, setExtractResults] = useState<BatchExtractResult | null>(null);
  const [selectedRepos, setSelectedRepos] = useState<Set<string>>(new Set());
  const [addingRepos, setAddingRepos] = useState(false);
  const [repoAddStatus, setRepoAddStatus] = useState<Record<string, RepoAddStatus>>({});
  const [imageFile, setImageFile] = useState<File | null>(null);

  /* ---- 工具函数 ---- */

  /**
   * 将 File 对象转为 base64 字符串
   * @param file 需要转换的文件对象
   * @returns base64 编码的 Data URL 字符串
   */
  const fileToBase64 = (file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  };

  /* ---- 核心操作 ---- */

  /**
   * 处理文件上传
   * 支持压缩包（.zip/.7z）和图片（.png/.jpg/.jpeg）两种类型
   */
  const handleFileUpload = async (file: File) => {
    /* 图片文件处理：限制 10MB，保存到 imageFile 状态 */
    const isImage = file.name.endsWith('.png') || file.name.endsWith('.jpg') || file.name.endsWith('.jpeg');
    if (isImage) {
      if (file.size > 10 * 1024 * 1024) {
        toast.error('图片超过 10MB 限制');
        return;
      }
      setImageFile(file);
      setExtractResult(null);
      setPreviewInfo(null);
      return;
    }

    /* 压缩包处理 */
    if (!file.name.endsWith('.zip') && !file.name.endsWith('.7z')) {
      toast.error('仅支持 .zip、.7z、.png、.jpg、.jpeg 格式');
      return;
    }
    if (file.size > 1024 * 1024 * 1024) {
      toast.error('压缩包超过 1GB 限制，请手动解压后通过 GitHub 地址添加');
      return;
    }

    setUploading(true);
    setExtractResult(null);
    setPreviewInfo(null);

    try {
      const formData = new FormData();
      formData.append('file', file);

      const res = await fetch('/api/extract-zip', {
        method: 'POST',
        body: formData,
      });

      const data = await res.json();

      if (data.success) {
        setExtractResult(data);
      } else {
        toast.error(data.detail || '解析压缩包失败');
      }
    } catch (err) {
      log.error('Failed to upload zip:', err);
      toast.error('上传压缩包失败');
    } finally {
      setUploading(false);
    }
  };

  /**
   * 确认添加压缩包项目（新项目）
   */
  const handleConfirmAddFromZip = async () => {
    if (!extractResult) return;
    setAddingProject(true);
    try {
      const res = await fetch('/api/extract-zip/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tempId: extractResult.tempId,
          action: 'add',
          projectInfo: {
            name: extractResult.name,
            description: extractResult.description,
            readme: extractResult.readme,
            githubUrl: extractResult.githubUrl,
            versionType: extractResult.versionType,
            versionInfo: extractResult.versionInfo,
            commitSha: extractResult.commitSha,
            commitDate: extractResult.commitDate,
            latestVersion: extractResult.latestVersion,
            downloadUrl: extractResult.downloadUrl,
          },
          localStoragePath: localStoragePath || '',
          archiveFormat,
        }),
      });

      if (res.ok) {
        toast.success('项目添加成功');
        setExtractResult(null);
        loadProjects();
      } else {
        const data = await safeResJson(res);
        toast.error(data.detail || '添加失败');
      }
    } catch (err) {
      log.error('Failed to add from zip:', err);
      toast.error('添加失败');
    } finally {
      setAddingProject(false);
    }
  };

  /**
   * 确认覆盖已有项目（触发二次确认）
   */
  const handleConfirmOverwrite = () => {
    setShowOverwriteConfirm(true);
  };

  /**
   * 最终确认覆盖
   */
  const handleOverwriteFinal = async () => {
    if (!extractResult || !extractResult.duplicate.existingProject) return;
    setAddingProject(true);
    setShowOverwriteConfirm(false);
    try {
      const existingProject = extractResult.duplicate.existingProject;
      const res = await fetch('/api/extract-zip/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tempId: extractResult.tempId,
          action: 'overwrite',
          projectInfo: {
            name: extractResult.name,
            description: extractResult.description,
            readme: extractResult.readme,
            githubUrl: extractResult.githubUrl,
            versionType: extractResult.versionType,
            versionInfo: extractResult.versionInfo,
            commitSha: extractResult.commitSha,
            commitDate: extractResult.commitDate,
            latestVersion: extractResult.latestVersion,
            downloadUrl: extractResult.downloadUrl,
          },
          localStoragePath: localStoragePath || '',
          archiveFormat,
          existingProjectId: existingProject.id,
        }),
      });

      if (res.ok) {
        toast.success('项目覆盖成功');
        setExtractResult(null);
        loadProjects();
      } else {
        const data = await safeResJson(res);
        toast.error(data.detail || '覆盖失败');
      }
    } catch (err) {
      log.error('Failed to overwrite from zip:', err);
      toast.error('覆盖失败');
    } finally {
      setAddingProject(false);
    }
  };

  /**
   * 跳过压缩包项目
   */
  const handleSkipExtract = () => {
    setExtractResult(null);
  };

  /**
   * 执行批量提取（文章链接 + 图片 OCR）
   * 根据输入内容自动判断提取方式：文章链接走 URL 提取，图片走 OCR 提取
   */
  const handleBatchExtract = async () => {
    setExtracting(true);
    setExtractResults(null);
    try {
      const requestBody: Record<string, unknown> = {};

      /* 如果输入是文章链接（非 GitHub URL 的 HTTP 链接） */
      if (form.githubUrl.trim() && form.githubUrl.trim().startsWith('http') && !form.githubUrl.includes('github.com')) {
        requestBody.urls = [form.githubUrl.trim()];
      }

      /* 如果有图片文件，转为 base64 一起提交，并附带 LLM 配置用于 OCR */
      if (imageFile) {
        const base64 = await fileToBase64(imageFile);
        requestBody.files = [{ name: imageFile.name, data: base64 }];
        const currentProvider = providersConfig[providerId];
        requestBody.providerId = providerId;
        requestBody.modelId = modelId;
        requestBody.apiKey = currentProvider?.apiKey ?? '';
        requestBody.baseUrl = currentProvider?.baseUrl || currentProvider?.defaultBaseUrl || '';
      }

      const res = await fetch('/api/extract/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
      });

      const data = await res.json();
      if (data.code === 200) {
        setExtractResults(data.data);
        /* 默认选中所有未存在于数据库的仓库 */
        const defaultSelected = new Set<string>();
        (data.data as BatchExtractResult).repos.forEach((repo) => {
          if (!repo.existsInDb) defaultSelected.add(repo.url);
        });
        setSelectedRepos(defaultSelected);
      } else {
        toast.error(data.message || '提取失败');
      }
    } catch {
      toast.error('批量提取失败');
    } finally {
      setExtracting(false);
    }
  };

  /**
   * 批量添加选中的仓库到 Gitter 项目
   * 逐个获取 GitHub 信息并创建项目
   */
  const handleBatchAdd = async () => {
    if (!extractResults || selectedRepos.size === 0) return;
    setAddingRepos(true);
    let successCount = 0;
    let failCount = 0;

    /* 初始化所有选中仓库的状态为 pending */
    const initialStatus: Record<string, RepoAddStatus> = {};
    for (const repo of extractResults.repos) {
      if (selectedRepos.has(repo.url)) initialStatus[repo.url] = 'pending';
    }
    setRepoAddStatus(initialStatus);

    for (const repo of extractResults.repos) {
      if (!selectedRepos.has(repo.url)) continue;

      /* 标记当前仓库为 adding */
      setRepoAddStatus((prev) => ({ ...prev, [repo.url]: 'adding' }));

      try {
        /* 获取仓库详细信息 */
        const res = await fetch('/api/github-info?url=' + encodeURIComponent(repo.url));
        const info = await res.json();

        if (res.ok) {
          /* 创建项目（路径由后端自动处理） */
          const createRes = await fetch('/api/projects', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              name: info.name,
              description: info.description,
              readme: info.readme,
              github_url: info.githubUrl,
              local_path: null,
              version_type: info.versionType,
              latest_version: info.latestVersion,
              current_version: info.latestVersion,
              download_url: info.downloadUrl,
              commit_sha: info.commitSha,
              commit_date: info.commitDate,
              sync_status: 'synced',
            }),
          });

          if (createRes.ok) {
            successCount++;
            setRepoAddStatus((prev) => ({ ...prev, [repo.url]: 'success' }));
          } else {
            failCount++;
            setRepoAddStatus((prev) => ({ ...prev, [repo.url]: 'failed' }));
          }
        } else {
          failCount++;
          setRepoAddStatus((prev) => ({ ...prev, [repo.url]: 'failed' }));
        }
      } catch {
        failCount++;
        setRepoAddStatus((prev) => ({ ...prev, [repo.url]: 'failed' }));
      }
    }

    toast.success(`已成功添加 ${successCount} 个项目${failCount > 0 ? `，失败 ${failCount} 个` : ''}`);
    /* 重置提取状态 */
    setExtractResults(null);
    setSelectedRepos(new Set());
    setRepoAddStatus({});
    setImageFile(null);
    setForm(initialFormState);
    loadProjects();
    setAddingRepos(false);
  };

  return {
    uploading,
    extractResult,
    setExtractResult,
    showOverwriteConfirm,
    setShowOverwriteConfirm,
    fileInputRef,
    dragOver,
    setDragOver,
    extracting,
    extractResults,
    setExtractResults,
    selectedRepos,
    setSelectedRepos,
    addingRepos,
    repoAddStatus,
    setRepoAddStatus,
    imageFile,
    setImageFile,
    handleFileUpload,
    handleConfirmAddFromZip,
    handleConfirmOverwrite,
    handleOverwriteFinal,
    handleSkipExtract,
    handleBatchExtract,
    handleBatchAdd,
  };
}
