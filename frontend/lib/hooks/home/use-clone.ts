'use client';

import { useState, useRef } from 'react';
import type { Project } from '@/lib/types';
import type { GithubInfo } from '@/lib/types/home';
import { initialFormState } from '@/lib/types/home';
import { safeResJson } from '@/lib/utils/home';
import { createLogger } from '@/lib/logger';
import { toast } from 'sonner';
import { useSettingsStore } from '@/lib/store/settings';

const log = createLogger('useClone');

/**
 * 克隆/拉取/工作流轮询 Hook
 * 管理项目的 Git 克隆、拉取、工作流进度轮询及一键更新
 *
 * @param deps 外部依赖：项目列表刷新函数、预览信息、表单状态
 */
export function useClone(deps: {
  loadProjects: () => Promise<void>;
  previewInfo: GithubInfo | null;
  setPreviewInfo: (info: GithubInfo | null) => void;
  form: { githubUrl: string };
  setForm: (form: { githubUrl: string }) => void;
}) {
  const { loadProjects, previewInfo, setPreviewInfo, form, setForm } = deps;

  /* 从持久化 store 读取 Git 相关配置 */
  const gitProxy = useSettingsStore((state) => state.gitProxy);
  const localStoragePath = useSettingsStore((state) => state.localStoragePath);
  const archiveFormat = useSettingsStore((state) => state.archiveFormat);
  const gitPath = useSettingsStore((state) => state.gitPath);
  const cloneMethod = useSettingsStore((state) => state.cloneMethod);
  const ghPath = useSettingsStore((state) => state.ghPath);
  const mirrorUrl = useSettingsStore((state) => state.mirrorUrl);
  const translateModel = useSettingsStore((state) => `${state.providerId}:${state.modelId}`);
  const providersConfig = useSettingsStore((state) => state.providersConfig);

  /* ---- 状态 ---- */
  const [cloningId, setCloningId] = useState<number | null>(null);
  const [pullingId, setPullingId] = useState<number | null>(null);
  const [addingProject, setAddingProject] = useState(false);
  const [addProjectStep, setAddProjectStep] = useState(0);
  const [workflowProjectId, setWorkflowProjectId] = useState<number | null>(null);
  const [workflowStatus, setWorkflowStatus] = useState<string>('idle');
  const workflowRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /**
   * 启动工作流进度轮询
   * 每隔 3 秒查询项目工作流状态，直到完成或失败
   */
  const startWorkflowPolling = (projectId: number) => {
    if (workflowRef.current) clearInterval(workflowRef.current);
    setWorkflowProjectId(projectId);
    setWorkflowStatus('cloning');

    workflowRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/projects/${projectId}/workflow-status`);
        if (res.ok) {
          const data = await res.json();
          const status = data.workflowStatus || 'idle';
          setWorkflowStatus(status);
          if (status === 'done' || status === 'failed') {
            stopWorkflowPolling();
            if (status === 'done') {
              loadProjects();
            }
          }
        }
      } catch {
        // 忽略轮询错误
      }
    }, 3000);
  };

  /** 停止工作流轮询 */
  const stopWorkflowPolling = () => {
    if (workflowRef.current) {
      clearInterval(workflowRef.current);
      workflowRef.current = null;
    }
  };

  /**
   * 确认添加项目（含 git clone）
   */
  const handleAddProject = async () => {
    if (!previewInfo) return;
    setAddingProject(true);
    setAddProjectStep(1);
    try {
      const res = await fetch('/api/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: previewInfo.name,
          description: previewInfo.description,
          readme: previewInfo.readme,
          github_url: previewInfo.githubUrl,
          local_path: null,
          version_type: previewInfo.versionType,
          latest_version: previewInfo.latestVersion,
          current_version: previewInfo.latestVersion,
          download_url: previewInfo.downloadUrl,
          commit_sha: previewInfo.commitSha,
          commit_date: previewInfo.commitDate,
          sync_status: 'synced',
        }),
      });
      if (res.ok) {
        const project = await res.json();
        setAddProjectStep(2);

        try {
          const cloneRes = await fetch(`/api/projects/${project.id}/clone`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ proxy: gitProxy, localStoragePath: localStoragePath || '', archiveFormat, gitPath: gitPath || '', cloneMethod, ghPath: ghPath || '', mirrorUrl: mirrorUrl || '' }),
          });
          if (cloneRes.ok) {
            setAddProjectStep(3);
            // 启动工作流进度轮询（后台自动执行：graphify→bridge→wiki compile）
            startWorkflowPolling(project.id);
            toast.success('项目已添加，正在后台构建知识图谱...');
          } else {
            const cloneData = await safeResJson(cloneRes);
            const detail = cloneData.detail || '未知错误';
            toast.warning('项目已添加，但克隆失败', {
              description: detail,
              duration: 10000,
            });
          }
        } catch (cloneErr) {
          toast.warning('项目已添加，但克隆失败');
        }

        setForm(initialFormState);
        setPreviewInfo(null);
        loadProjects();
      } else {
        const data = await safeResJson(res);
        toast.error(data.detail || '添加失败');
      }
    } catch (err) {
      log.error('Failed to add project:', err);
      toast.error('添加失败');
    } finally {
      setAddingProject(false);
      setAddProjectStep(0);
    }
  };

  /**
   * 克隆项目到本地
   */
  const handleCloneProject = async (project: Project) => {
    setCloningId(project.id);
    try {
      const res = await fetch(`/api/projects/${project.id}/clone`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proxy: gitProxy, localStoragePath: localStoragePath || '', archiveFormat, gitPath: gitPath || '', cloneMethod, ghPath: ghPath || '', mirrorUrl: mirrorUrl || '' }),
      });
      if (res.ok) {
        toast.success('克隆成功');
        loadProjects();
      } else {
        const data = await safeResJson(res);
        toast.error('克隆失败', {
          description: data.detail || '未知错误',
          duration: 10000,
        });
      }
    } catch (err) {
      log.error('Failed to clone project:', err);
      toast.error('克隆失败', {
        description: String(err),
        duration: 10000,
      });
    } finally {
      setCloningId(null);
    }
  };

  /**
   * 拉取项目最新代码（git pull，含3次重试）
   */
  const handlePullProject = async (project: Project) => {
    setPullingId(project.id);
    try {
      const res = await fetch(`/api/projects/${project.id}/pull`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proxy: gitProxy, gitPath: gitPath || '', cloneMethod, ghPath: ghPath || '', mirrorUrl: mirrorUrl || '' }),
      });
      if (res.ok) {
        toast.success('更新成功，正在后台构建知识图谱...');
        // 启动工作流进度轮询
        startWorkflowPolling(project.id);
        loadProjects();
      } else {
        const data = await safeResJson(res);
        toast.error(data.detail || '更新失败');
        loadProjects();
      }
    } catch (err) {
      log.error('Failed to pull project:', err);
      toast.error('更新失败');
    } finally {
      setPullingId(null);
    }
  };

  /**
   * 一键更新所有项目
   */
  const handleUpdateAll = async () => {
    toast.info('开始更新所有项目...');
    try {
      const [pId, ...modelParts] = translateModel.split(':');
      const mId = modelParts.join(':');
      const config = providersConfig?.[pId as keyof typeof providersConfig];
      const apiKey = config?.apiKey || '';
      const baseUrl = config?.baseUrl || config?.defaultBaseUrl || '';

      const res = await fetch('/api/update-all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: translateModel, apiKey, baseUrl }),
      });
      if (res.ok) {
        const result = await res.json();
        toast.success(`更新完成: ${result.success} 成功, ${result.failed} 失败`);
        loadProjects();
      } else {
        toast.error('更新失败');
      }
    } catch (err) {
      log.error('Failed to update all:', err);
      toast.error('更新失败');
    }
  };

  return {
    cloningId,
    pullingId,
    addingProject,
    setAddingProject,
    addProjectStep,
    workflowProjectId,
    workflowStatus,
    handleAddProject,
    handleCloneProject,
    handlePullProject,
    handleUpdateAll,
    startWorkflowPolling,
    stopWorkflowPolling,
  };
}
