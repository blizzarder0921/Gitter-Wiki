'use client';

import { useState, useEffect } from 'react';
import { useSettingsStore } from '@/lib/store/settings';
import type { ProviderId } from '@/lib/ai/providers';
import type { Project } from '@/lib/types';
import { createLogger } from '@/lib/logger';
import { toast } from 'sonner';
import { safeResJson } from '@/lib/utils/home';

const log = createLogger('Translate');

/**
 * 翻译模型选择与项目翻译 Hook
 * 管理翻译模型选择状态，提供项目描述/README 的翻译功能
 * @param loadProjects 项目列表刷新函数
 * @param setDetailProject 详情项目状态更新函数（用于翻译后实时更新详情弹窗）
 */
export function useTranslate(
  loadProjects: () => Promise<void>,
  setDetailProject?: React.Dispatch<React.SetStateAction<Project | null>>,
) {
  /* 翻译模型 ID（格式：providerId:modelId） */
  const [translateModel, setTranslateModel] = useState<string>('');
  /* 翻译目标语言 */
  const [translateTargetLang, setTranslateTargetLang] = useState<'zh' | 'en'>('zh');
  /* 当前正在翻译的项目 ID */
  const [translatingId, setTranslatingId] = useState<number | null>(null);

  /* 从持久化 store 读取配置 */
  const providersConfig = useSettingsStore((state) => state.providersConfig);
  const persistedProviderId = useSettingsStore((state) => state.providerId);
  const persistedModelId = useSettingsStore((state) => state.modelId);
  const setModel = useSettingsStore((state) => state.setModel);

  /**
   * 从持久化 store 初始化模型选择
   * 当 store 中的 providerId/modelId 变化时同步到本地状态
   */
  useEffect(() => {
    if (persistedProviderId && persistedModelId) {
      setTranslateModel(`${persistedProviderId}:${persistedModelId}`);
    }
  }, [persistedProviderId, persistedModelId]);

  /**
   * 模型选择变更时同步回持久化 store
   * 将 "providerId:modelId" 格式的字符串拆解并存储
   * @param value 格式为 "providerId:modelId" 的模型标识字符串
   */
  const handleTranslateModelChange = (value: string) => {
    setTranslateModel(value);
    const [pid, ...modelParts] = value.split(':');
    const mid = modelParts.join(':');
    if (pid && mid) {
      setModel(pid as ProviderId, mid);
    }
  };

  /**
   * 执行项目翻译（描述 + README）
   * 将项目的 description 和 readme 翻译到目标语言并保存
   * @param project 目标项目
   * @param targetLang 目标语言 'zh' | 'en'
   */
  const handleTranslateProject = async (project: Project, targetLang: 'zh' | 'en' = 'zh') => {
    if (!translateModel) {
      toast.error('请先选择翻译模型');
      return;
    }
    setTranslatingId(project.id);
    try {
      const [pId, ...modelParts] = translateModel.split(':');
      const mId = modelParts.join(':');
      const config = providersConfig?.[pId as keyof typeof providersConfig];
      const apiKey = config?.apiKey || '';
      const baseUrl = config?.baseUrl || config?.defaultBaseUrl || '';

      const updates: Record<string, string | null> = {};

      /* 翻译项目描述 */
      if (project.description) {
        const descRes = await fetch(`/api/translate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: project.description, providerId: pId, modelId: mId, apiKey, baseUrl, targetLang }),
        });
        if (descRes.ok) {
          const descData = await descRes.json();
          if (descData.translatedText) updates.description = descData.translatedText;
        }
      }

      /* 翻译 README */
      if (project.readme) {
        const readmeRes = await fetch(`/api/translate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: project.readme, providerId: pId, modelId: mId, apiKey, baseUrl, targetLang }),
        });
        if (readmeRes.ok) {
          const readmeData = await readmeRes.json();
          if (readmeData.translatedText) updates.readme = readmeData.translatedText;
        }
      }

      /* PATCH 更新项目并刷新列表 */
      if (Object.keys(updates).length > 0) {
        const patchRes = await fetch(`/api/projects/${project.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(updates),
        });
        if (patchRes.ok) {
          toast.success('翻译成功');
          loadProjects();
          /* 实时更新详情弹窗内容 */
          setDetailProject?.((prev) => prev ? { ...prev, ...updates } : null);
        } else {
          toast.error('保存失败');
        }
      } else {
        toast.error('翻译结果为空');
      }
    } catch (err) {
      log.error('Failed to translate:', err);
      toast.error('翻译失败');
    } finally {
      setTranslatingId(null);
    }
  };

  return {
    translateModel,
    handleTranslateModelChange,
    translateTargetLang,
    translatingId,
    handleTranslateProject,
  };
}
