import type { ProviderId, ModelInfo, ProviderType } from '@/lib/types/provider';

/** 设置面板可用的导航分区 */
export type SettingsSection = 'general' | 'providers' | 'wiki' | 'research' | 'evolution' | 'storage' | 'share';

/**
 * 统一的提供商配置存储格式
 * 内置和自定义提供商共用同一结构
 */
export interface ProviderSettings {
  /** API 密钥 */
  apiKey: string;
  /** 接口基础 URL */
  baseUrl: string;
  /** 该提供商下的所有模型列表 */
  models: ModelInfo[];

  /** 提供商元数据 */
  name: string;
  type: ProviderType;
  defaultBaseUrl?: string;
  icon?: string;
  requiresApiKey: boolean;
  isBuiltIn: boolean;
}

/**
 * 提供商配置映射表
 * Key: providerId, Value: ProviderSettings
 */
export type ProvidersConfig = Record<ProviderId, ProviderSettings>;

/** 正在编辑的模型信息 */
export interface EditingModel {
  providerId: ProviderId;
  modelIndex: number | null;
  model: ModelInfo;
}
