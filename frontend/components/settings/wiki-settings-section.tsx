'use client';

/**
 * Wiki 引擎设置面板 -- wiki-settings-section.tsx
 *
 * 提供 Wiki 引擎的输出语言、上下文窗口大小、向量检索（RAG）等参数配置。
 * 向量检索开启后，展示 Embedding 模型名称、API 端点地址、API 密钥的输入框。
 * 设置数据通过 useSettingsStore 持久化至 SQLite。
 *
 * 依赖：
 *   - @/lib/store/settings：全局设置状态管理
 *   - @/lib/wiki/types：OutputLanguage 类型定义
 *   - @/components/ui/select：下拉选择器组件
 *   - @/components/ui/switch：开关组件
 *   - @/components/ui/input：文本输入组件
 *   - @/components/ui/button：按钮组件
 */

import { useState } from 'react';
import { Globe, Maximize, Database, Eye, EyeOff } from 'lucide-react';
import { useSettingsStore } from '@/lib/store/settings';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import type { OutputLanguage } from '@/lib/wiki/types';

// ---------------------------------------------------------------------------
// 常量定义
// ---------------------------------------------------------------------------

/** 输出语言选项：value 对应 OutputLanguage 类型，label 为展示文本 */
const LANGUAGE_OPTIONS: { value: OutputLanguage; label: string }[] = [
  { value: 'auto', label: '自动检测' },
  { value: 'Chinese', label: '简体中文' },
  { value: 'English', label: 'English' },
  { value: 'Japanese', label: '日本語' },
  { value: 'Korean', label: '한국어' },
  { value: 'French', label: 'Français' },
  { value: 'German', label: 'Deutsch' },
  { value: 'Spanish', label: 'Español' },
  { value: 'Portuguese', label: 'Português' },
  { value: 'Italian', label: 'Italiano' },
  { value: 'Russian', label: 'Русский' },
  { value: 'Arabic', label: 'العربية' },
  { value: 'Persian', label: 'فارسی' },
  { value: 'Hindi', label: 'हिन्दी' },
  { value: 'Turkish', label: 'Türkçe' },
  { value: 'Dutch', label: 'Nederlands' },
  { value: 'Polish', label: 'Polski' },
  { value: 'Swedish', label: 'Svenska' },
  { value: 'Indonesian', label: 'Bahasa Indonesia' },
  { value: 'Thai', label: 'ไทย' },
  { value: 'Ukrainian', label: 'Українська' },
  { value: 'Vietnamese', label: 'Tiếng Việt' },
  { value: 'Traditional Chinese', label: '繁體中文' },
];

/**
 * 上下文窗口选项列表
 * 值以 tokens 为单位，控制 LLM 处理输入的最大长度
 */
const CONTEXT_WINDOW_OPTIONS: { value: number; label: string }[] = [
  { value: 4096, label: '4K tokens' },
  { value: 8192, label: '8K tokens' },
  { value: 16384, label: '16K tokens' },
  { value: 32768, label: '32K tokens' },
  { value: 131072, label: '128K tokens' },
  { value: 1048576, label: '1M tokens' },
];

// ---------------------------------------------------------------------------
// 主组件
// ---------------------------------------------------------------------------

/**
 * Wiki 引擎设置面板
 *
 * 布局与 GeneralSettings 保持一致：每个设置项使用独立的圆角卡片，
 * 包含图标标题区、描述文字和交互控件三部分。
 */
export function WikiSettingsSection() {
  /** Wiki 输出语言设置 */
  const wikiLanguage = useSettingsStore((state) => state.wikiLanguage);
  const setWikiLanguage = useSettingsStore((state) => state.setWikiLanguage);

  /** 上下文窗口大小设置 */
  const wikiContextWindow = useSettingsStore((state) => state.wikiContextWindow);
  const setWikiContextWindow = useSettingsStore((state) => state.setWikiContextWindow);

  /** 向量检索开关 */
  const wikiVectorEnabled = useSettingsStore((state) => state.wikiVectorEnabled);
  const setWikiVectorEnabled = useSettingsStore((state) => state.setWikiVectorEnabled);

  /** Embedding 模型名称 */
  const wikiEmbeddingModel = useSettingsStore((state) => state.wikiEmbeddingModel);
  const setWikiEmbeddingModel = useSettingsStore((state) => state.setWikiEmbeddingModel);

  /** Embedding API 端点地址 */
  const wikiEmbeddingEndpoint = useSettingsStore((state) => state.wikiEmbeddingEndpoint);
  const setWikiEmbeddingEndpoint = useSettingsStore((state) => state.setWikiEmbeddingEndpoint);

  /** Embedding API 密钥 */
  const wikiEmbeddingApiKey = useSettingsStore((state) => state.wikiEmbeddingApiKey);
  const setWikiEmbeddingApiKey = useSettingsStore((state) => state.setWikiEmbeddingApiKey);

  /** API 密钥明文显示切换 */
  const [showApiKey, setShowApiKey] = useState(false);

  return (
    <div className="flex flex-col gap-8">
      {/* 输出语言选择 */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="p-4 space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <Globe className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold">输出语言</h3>
          </div>
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              Wiki 生成内容时使用的语言，选择 &ldquo;自动检测&rdquo; 将根据输入自动匹配。
            </p>
            <Select
              value={wikiLanguage}
              onValueChange={(val) => setWikiLanguage(val as OutputLanguage)}
            >
              <SelectTrigger size="sm" className="w-56">
                <SelectValue placeholder="选择语言" />
              </SelectTrigger>
              <SelectContent>
                {LANGUAGE_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      {/* 上下文窗口选择 */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="p-4 space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <Maximize className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold">上下文窗口</h3>
          </div>
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              LLM 处理单次请求的最大 token 数。窗口越大，能处理的内容越多，但速度更慢且成本更高。
            </p>
            <Select
              value={String(wikiContextWindow)}
              onValueChange={(val) => setWikiContextWindow(Number(val))}
            >
              <SelectTrigger size="sm" className="w-44">
                <SelectValue placeholder="选择大小" />
              </SelectTrigger>
              <SelectContent>
                {CONTEXT_WINDOW_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={String(opt.value)}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      {/* 向量检索（RAG）开关 */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="p-4 space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <Database className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold">向量检索（RAG）</h3>
          </div>
          <div className="flex items-center justify-between gap-4">
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium">启用向量化语义搜索</p>
              <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
                开启后，Wiki 会对文档内容做向量化索引，支持语义相似度检索。
                需要配置 Embedding 模型与端点地址。
              </p>
            </div>
            <Switch
              checked={wikiVectorEnabled}
              onCheckedChange={setWikiVectorEnabled}
              className="shrink-0"
            />
          </div>

          {/* Embedding 配置面板 -- 仅当向量检索开启时显示 */}
          {wikiVectorEnabled && (
            <div className="space-y-3 pt-2 border-t border-border">
              <p className="text-xs font-medium text-muted-foreground">
                Embedding 模型配置
              </p>

              {/* Embedding 模型名称 */}
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-foreground">
                  Embedding 模型
                </label>
                <Input
                  value={wikiEmbeddingModel}
                  onChange={(e) => setWikiEmbeddingModel(e.target.value)}
                  placeholder="例如: BAAI/bge-m3, text-embedding-3-small"
                  className="h-8 text-xs"
                />
                <p className="text-[11px] text-muted-foreground">
                  填写模型完整名称，如 HuggingFace 模型需带命名空间前缀
                </p>
              </div>

              {/* Embedding API 端点 */}
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-foreground">
                  API 端点地址
                </label>
                <Input
                  value={wikiEmbeddingEndpoint}
                  onChange={(e) => setWikiEmbeddingEndpoint(e.target.value)}
                  placeholder="https://api.openai.com/v1/embeddings"
                  className="h-8 text-xs"
                />
                <p className="text-[11px] text-muted-foreground">
                  OpenAI 兼容的 Embedding API 地址，如使用默认 LLM 提供商可不填
                </p>
              </div>

              {/* Embedding API 密钥 */}
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-foreground">
                  API 密钥
                </label>
                <div className="flex gap-2">
                  <Input
                    type={showApiKey ? 'text' : 'password'}
                    value={wikiEmbeddingApiKey}
                    onChange={(e) => setWikiEmbeddingApiKey(e.target.value)}
                    placeholder="请输入 Embedding API 的密钥"
                    className="h-8 text-xs flex-1"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8 w-8 p-0 shrink-0"
                    onClick={() => setShowApiKey(!showApiKey)}
                    aria-label={showApiKey ? '隐藏密钥' : '显示密钥'}
                  >
                    {showApiKey ? (
                      <EyeOff className="w-3.5 h-3.5" />
                    ) : (
                      <Eye className="w-3.5 h-3.5" />
                    )}
                  </Button>
                </div>
                <p className="text-[11px] text-muted-foreground">
                  Embedding 服务提供商对应的 API 密钥
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
