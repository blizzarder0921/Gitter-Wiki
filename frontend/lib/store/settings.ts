/**
 * Settings Store
 * Gitter 项目全局设置状态，同步至 SQLite
 * 仅保留 LLM 提供商配置、模型选择、本地存储路径等核心状态
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import dbStorage from '@/lib/store/db-storage';
import type { ProviderId } from '@/lib/ai/providers';
import type { ProvidersConfig } from '@/lib/types/settings';
import { PROVIDERS } from '@/lib/ai/providers';
import type { ThinkingConfig } from '@/lib/types/provider';
import { getThinkingConfigKey, supportsConfigurableThinking } from '@/lib/ai/thinking-config';
import type { OutputLanguage } from '@/lib/wiki/types';
import { createLogger } from '@/lib/logger';

const log = createLogger('Settings');

/** 分享文案 Agent 默认提示词，供设置面板"恢复默认"功能使用 */
export const DEFAULT_SHARE_AGENT_PROMPT = `你是一位专业的开源项目推广文案撰写专家。你的任务是根据用户提供的项目信息，撰写引人入胜的宣传文案。

要求：
1. 文案必须基于项目真实信息，不得虚构功能或数据
2. 突出项目核心亮点和差异化优势
3. 语言风格根据用户选择的风格类型调整
4. 文案结构清晰，易于阅读
5. 包含项目 GitHub 链接

输出格式：
- 使用 Markdown 格式
- 在文案末尾单独输出配图提示词，格式为：## 🎨 配图提示词\n> [提示词内容]`;

/**
 * 裁剪无效的 ThinkingConfig 条目
 * 仅保留当前 providersConfig 中仍存在的模型对应的配置
 */
function pruneThinkingConfigs(
  thinkingConfigs: Record<string, ThinkingConfig> | undefined,
  providersConfig: ProvidersConfig | undefined,
): Record<string, ThinkingConfig> {
  if (!thinkingConfigs || !providersConfig) return {};

  const validKeys = new Set<string>();
  for (const [providerId, providerConfig] of Object.entries(providersConfig)) {
    for (const model of providerConfig.models) {
      if (supportsConfigurableThinking(model.capabilities?.thinking)) {
        validKeys.add(getThinkingConfigKey(providerId, model.id));
      }
    }
  }

  return Object.fromEntries(
    Object.entries(thinkingConfigs).filter(([key]) => validKeys.has(key)),
  ) as Record<string, ThinkingConfig>;
}

export interface SettingsState {
  /** 当前选中的 LLM 提供商 ID */
  providerId: ProviderId;
  /** 当前选中的模型 ID */
  modelId: string;
  /** 各模型的 Thinking 配置映射 */
  thinkingConfigs: Record<string, ThinkingConfig>;

  /** 提供商配置（统一 JSON 存储） */
  providersConfig: ProvidersConfig;

  /** 自动配置生命周期标记（持久化） */
  autoConfigApplied: boolean;

  /** 项目本地存储路径 */
  localStoragePath: string;

  /** Git 代理地址（如 http://127.0.0.1:7890），为空则不使用代理 */
  gitProxy: string;

  /** Git 可执行文件路径（绿色版 Git），为空则使用系统 PATH 中的 git */
  gitPath: string;

  /** 克隆方式：https（默认）、ssh、gh_cli、mirror */
  cloneMethod: 'https' | 'ssh' | 'gh_cli' | 'mirror';

  /** GitHub CLI 可执行文件路径（自定义安装位置），为空则使用系统 PATH 中的 gh */
  ghPath: string;

  /** GitHub 镜像加速地址，如 https://ghproxy.com 或 hub.fastgit.xyz */
  mirrorUrl: string;

  /** GitHub Personal Access Token，用于提高 API 限额（未认证 60 次/小时，认证 5000 次/小时） */
  githubToken: string;

  /** 版本归档压缩格式：zip 或 7z */
  archiveFormat: 'zip' | '7z';

  /** Wiki 引擎 - 输出语言 */
  wikiLanguage: OutputLanguage;
  /** Wiki 引擎 - 上下文窗口大小（tokens） */
  wikiContextWindow: number;
  /** Wiki 引擎 - 是否启用向量检索（RAG） */
  wikiVectorEnabled: boolean;
  /** Wiki 引擎 - Embedding 模型名称 */
  wikiEmbeddingModel: string;
  /** Wiki 引擎 - Embedding API 端点地址 */
  wikiEmbeddingEndpoint: string;
  /** Wiki 引擎 - Embedding API 密钥 */
  wikiEmbeddingApiKey: string;

  /** 深度研究 - 搜索提供商 */
  researchSearchProvider: 'tavily' | 'serpapi' | 'none';
  /** 深度研究 - API 密钥 */
  researchApiKey: string;
  /** 深度研究 - 最大并发任务数 */
  researchMaxConcurrent: number;

  /** 自动进化 - Git 变更自动摄入 */
  evolutionGitAutoIngest: boolean;
  /** 自动进化 - 定时 Lint 扫描频率 */
  evolutionLintSchedule: 'daily' | 'weekly' | 'off';
  /** 自动进化 - 概念过时检测 */
  evolutionStalenessCheck: boolean;
  /** 自动进化 - 跨项目关联分析 */
  evolutionCrossProject: boolean;

  /** 界面 - 代码高亮主题 */
  uiCodeTheme: string;
  /** 界面 - 数学公式渲染 */
  uiMathRender: boolean;

  /** 存储 - 向量索引存储路径 */
  storageVectorPath: string;
  /** 存储 - 对话历史保留策略 */
  storageChatRetention: '30d' | '90d' | 'forever';
  /** 存储 - 自动清理旧版本 */
  storageAutoCleanup: boolean;

  /** 分享文案 - Agent 角色提示词 */
  shareAgentPrompt: string;
  /** 分享文案 - 默认文案风格 */
  shareDefaultStyle: string;

  /** 设置当前模型 */
  setModel: (providerId: ProviderId, modelId: string) => void;
  /** 设置指定模型的 Thinking 配置 */
  setThinkingConfig: (
    providerId: ProviderId,
    modelId: string,
    config: ThinkingConfig | undefined,
  ) => void;
  /** 更新单个提供商的配置 */
  setProviderConfig: (providerId: ProviderId, config: Partial<ProvidersConfig[ProviderId]>) => void;
  /** 替换整个 providersConfig */
  setProvidersConfig: (config: ProvidersConfig) => void;
  /** 设置本地存储路径 */
  setLocalStoragePath: (path: string) => void;
  /** 设置 Git 代理地址 */
  setGitProxy: (proxy: string) => void;
  /** 设置 Git 可执行文件路径 */
  setGitPath: (path: string) => void;
  /** 设置克隆方式 */
  setCloneMethod: (method: 'https' | 'ssh' | 'gh_cli' | 'mirror') => void;
  /** 设置 GitHub CLI 可执行文件路径 */
  setGhPath: (path: string) => void;
  /** 设置 GitHub 镜像加速地址 */
  setMirrorUrl: (url: string) => void;
  /** 设置 GitHub Token */
  setGithubToken: (token: string) => void;
  /** 设置版本归档压缩格式 */
  setArchiveFormat: (format: 'zip' | '7z') => void;
  /** 设置 Wiki 输出语言 */
  setWikiLanguage: (language: OutputLanguage) => void;
  /** 设置 Wiki 上下文窗口大小 */
  setWikiContextWindow: (size: number) => void;
  /** 设置 Wiki 向量检索开关 */
  setWikiVectorEnabled: (enabled: boolean) => void;
  /** 设置 Wiki Embedding 模型名称 */
  setWikiEmbeddingModel: (model: string) => void;
  /** 设置 Wiki Embedding API 端点 */
  setWikiEmbeddingEndpoint: (endpoint: string) => void;
  /** 设置 Wiki Embedding API 密钥 */
  setWikiEmbeddingApiKey: (apiKey: string) => void;

  /** 设置深度研究搜索提供商 */
  setResearchSearchProvider: (provider: 'tavily' | 'serpapi' | 'none') => void;
  /** 设置深度研究 API 密钥 */
  setResearchApiKey: (key: string) => void;
  /** 设置深度研究最大并发数 */
  setResearchMaxConcurrent: (n: number) => void;

  /** 设置 Git 变更自动摄入开关 */
  setEvolutionGitAutoIngest: (enabled: boolean) => void;
  /** 设置 Lint 扫描频率 */
  setEvolutionLintSchedule: (schedule: 'daily' | 'weekly' | 'off') => void;
  /** 设置概念过时检测开关 */
  setEvolutionStalenessCheck: (enabled: boolean) => void;
  /** 设置跨项目关联分析开关 */
  setEvolutionCrossProject: (enabled: boolean) => void;

  /** 设置代码高亮主题 */
  setUiCodeTheme: (theme: string) => void;
  /** 设置数学公式渲染开关 */
  setUiMathRender: (enabled: boolean) => void;

  /** 设置向量索引存储路径 */
  setStorageVectorPath: (path: string) => void;
  /** 设置对话历史保留策略 */
  setStorageChatRetention: (retention: '30d' | '90d' | 'forever') => void;
  /** 设置自动清理旧版本开关 */
  setStorageAutoCleanup: (enabled: boolean) => void;

  /** 设置分享文案 Agent 提示词 */
  setShareAgentPrompt: (prompt: string) => void;
  /** 设置分享文案默认风格 */
  setShareDefaultStyle: (style: string) => void;
}

/**
 * 生成默认的 providersConfig，包含所有内置提供商
 */
const getDefaultProvidersConfig = (): ProvidersConfig => {
  const config: ProvidersConfig = {} as ProvidersConfig;
  Object.keys(PROVIDERS).forEach((pid) => {
    const provider = PROVIDERS[pid as ProviderId];
    config[pid as ProviderId] = {
      apiKey: '',
      baseUrl: '',
      models: provider.models,
      name: provider.name,
      type: provider.type,
      defaultBaseUrl: provider.defaultBaseUrl,
      icon: provider.icon,
      requiresApiKey: provider.requiresApiKey,
      isBuiltIn: true,
    };
  });
  return config;
};

/**
 * 确保 providersConfig 包含所有内置提供商
 * 仅添加用户尚未配置的新提供商，不强制合并模型列表
 * 所有模型（内置/自定义）均由用户手动管理
 */
function ensureBuiltInProviders(state: Partial<SettingsState>): void {
  if (!state.providersConfig) return;
  const defaultConfig = getDefaultProvidersConfig();
  Object.keys(PROVIDERS).forEach((pid) => {
    const providerId = pid as ProviderId;
    if (!state.providersConfig![providerId]) {
      state.providersConfig![providerId] = defaultConfig[providerId];
    } else {
      const provider = PROVIDERS[providerId];
      const existing = state.providersConfig![providerId];

      state.providersConfig![providerId] = {
        ...existing,
        name: existing.name || provider.name,
        type: existing.type || provider.type,
        defaultBaseUrl: existing.defaultBaseUrl || provider.defaultBaseUrl,
        icon: provider.icon || existing.icon,
        requiresApiKey: existing.requiresApiKey ?? provider.requiresApiKey,
        isBuiltIn: existing.isBuiltIn ?? true,
      };
    }
  });
}

/**
 * 自定义提供商历史兼容：将 defaultBaseUrl 提升为 baseUrl
 */
export function promoteLegacyCustomProviderBaseUrls(state: Partial<SettingsState>): void {
  if (!state.providersConfig) return;

  Object.values(state.providersConfig).forEach((config) => {
    if (!config.isBuiltIn && !config.baseUrl && config.defaultBaseUrl) {
      config.baseUrl = config.defaultBaseUrl;
    }
  });
}

/**
 * 从旧版存储格式迁移数据（已废弃，保留空函数以防迁移版本号不匹配）
 */
const migrateFromOldStorage = () => {
  return null;
};

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set, get) => ({
      providerId: 'openai',
      modelId: 'gpt-4o-mini',
      thinkingConfigs: {},
      providersConfig: getDefaultProvidersConfig(),
      autoConfigApplied: false,
      localStoragePath: '',
      gitProxy: '',
      gitPath: '',
      cloneMethod: 'https' as const,
      ghPath: '',
      mirrorUrl: 'https://ghproxy.com',
      githubToken: '',
      archiveFormat: 'zip',
      wikiLanguage: 'auto' as OutputLanguage,
      wikiContextWindow: 8000,
      wikiVectorEnabled: false,
      wikiEmbeddingModel: 'text-embedding-3-small',
      wikiEmbeddingEndpoint: '',
      wikiEmbeddingApiKey: '',
      researchSearchProvider: 'none' as const,
      researchApiKey: '',
      researchMaxConcurrent: 3,
      evolutionGitAutoIngest: true,
      evolutionLintSchedule: 'weekly' as const,
      evolutionStalenessCheck: false,
      evolutionCrossProject: false,
      uiCodeTheme: 'github-dark',
      uiMathRender: true,
      storageVectorPath: '',
      storageChatRetention: '90d' as const,
      storageAutoCleanup: false,
      shareAgentPrompt: DEFAULT_SHARE_AGENT_PROMPT,
      shareDefaultStyle: 'tech-review',

      setModel: (providerId, modelId) => set({ providerId, modelId }),

      setThinkingConfig: (providerId, modelId, config) =>
        set((state) => {
          const key = getThinkingConfigKey(providerId, modelId);
          const newConfigs = { ...state.thinkingConfigs };
          if (config === undefined) {
            delete newConfigs[key];
          } else {
            newConfigs[key] = config;
          }
          return { thinkingConfigs: pruneThinkingConfigs(newConfigs, state.providersConfig) };
        }),

      setProviderConfig: (providerId, config) =>
        set((state) => ({
          providersConfig: {
            ...state.providersConfig,
            [providerId]: { ...state.providersConfig[providerId], ...config },
          },
        })),

      setProvidersConfig: (config) => set({ providersConfig: config }),

      setLocalStoragePath: (newPath) =>
        set((state) => {
          const oldPath = state.localStoragePath;
          // 如果路径发生变更，触发项目迁移（通过 API 调用，避免客户端引入 better-sqlite3）
          if (oldPath !== newPath && oldPath && newPath) {
            // 异步调用迁移 API（不阻塞状态更新）
            fetch('/api/settings/migrate-projects', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ oldPath, newPath }),
            })
              .then((res) => res.json())
              .then((result) => {
                if (result.migrated > 0 || result.failed > 0) {
                  log.info(
                    `项目迁移完成: 成功 ${result.migrated}, 失败 ${result.failed}, 跳过 ${result.skipped}`,
                  );
                }
              })
              .catch((err) => {
                log.error('项目迁移失败:', err);
              });
          }
          return { localStoragePath: newPath };
        }),

      setGitProxy: (proxy) => set({ gitProxy: proxy }),
      setGitPath: (path) => set({ gitPath: path }),
      setCloneMethod: (method) => set({ cloneMethod: method }),
      setGhPath: (path) => set({ ghPath: path }),
      setMirrorUrl: (url) => set({ mirrorUrl: url }),
      setGithubToken: (token) => set({ githubToken: token }),

      setArchiveFormat: (format) => set({ archiveFormat: format }),

      setWikiLanguage: (language) => set({ wikiLanguage: language }),
      setWikiContextWindow: (size) => set({ wikiContextWindow: size }),
      setWikiVectorEnabled: (enabled) => set({ wikiVectorEnabled: enabled }),
      setWikiEmbeddingModel: (model) => set({ wikiEmbeddingModel: model }),
      setWikiEmbeddingEndpoint: (endpoint) => set({ wikiEmbeddingEndpoint: endpoint }),
      setWikiEmbeddingApiKey: (apiKey) => set({ wikiEmbeddingApiKey: apiKey }),
      setResearchSearchProvider: (provider) => set({ researchSearchProvider: provider }),
      setResearchApiKey: (key) => set({ researchApiKey: key }),
      setResearchMaxConcurrent: (n) => set({ researchMaxConcurrent: n }),
      setEvolutionGitAutoIngest: (enabled) => set({ evolutionGitAutoIngest: enabled }),
      setEvolutionLintSchedule: (schedule) => set({ evolutionLintSchedule: schedule }),
      setEvolutionStalenessCheck: (enabled) => set({ evolutionStalenessCheck: enabled }),
      setEvolutionCrossProject: (enabled) => set({ evolutionCrossProject: enabled }),
      setUiCodeTheme: (theme) => set({ uiCodeTheme: theme }),
      setUiMathRender: (enabled) => set({ uiMathRender: enabled }),
      setStorageVectorPath: (path) => set({ storageVectorPath: path }),
      setStorageChatRetention: (retention) => set({ storageChatRetention: retention }),
      setStorageAutoCleanup: (enabled) => set({ storageAutoCleanup: enabled }),
      setShareAgentPrompt: (prompt) => set({ shareAgentPrompt: prompt }),
      setShareDefaultStyle: (style) => set({ shareDefaultStyle: style }),
    }),
    {
      name: 'settings-storage',
      storage: createJSONStorage(() => dbStorage),
      version: 1,
      migrate: (persistedState: unknown, version: number) => {
        const state = persistedState as Partial<SettingsState>;

        if (version === 0) {
          const migration = migrateFromOldStorage();
          if (migration) {
            Object.assign(state, (migration as Record<string, unknown>).state);
          }
        }

        ensureBuiltInProviders(state);
        promoteLegacyCustomProviderBaseUrls(state);

        if (state.thinkingConfigs) {
          state.thinkingConfigs = pruneThinkingConfigs(
            state.thinkingConfigs,
            state.providersConfig,
          );
        }

        return state as SettingsState;
      },
      merge: (persistedState, currentState) => {
        const state = persistedState as Partial<SettingsState>;

        ensureBuiltInProviders(state);
        promoteLegacyCustomProviderBaseUrls(state);

        if (state.thinkingConfigs) {
          state.thinkingConfigs = pruneThinkingConfigs(
            state.thinkingConfigs,
            state.providersConfig,
          );
        }

        return {
          ...currentState,
          ...(state as SettingsState),
        };
      },
    },
  ),
);
