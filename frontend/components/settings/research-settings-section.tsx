'use client';

/**
 * 深度研究设置面板 -- research-settings-section.tsx
 *
 * 提供网络搜索提供商选择、API 密钥配置与最大并发任务数设置。
 * 深度研究功能使用外部搜索服务（Tavily/SerpApi）进行主题调研。
 *
 * 依赖：
 *   - @/lib/store/settings：全局设置状态管理
 */

import { Globe, Key, ListOrdered } from 'lucide-react';
import { useSettingsStore } from '@/lib/store/settings';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Input } from '@/components/ui/input';

export function ResearchSettings() {
  const searchProvider = useSettingsStore((s) => s.researchSearchProvider);
  const setSearchProvider = useSettingsStore((s) => s.setResearchSearchProvider);
  const apiKey = useSettingsStore((s) => s.researchApiKey);
  const setApiKey = useSettingsStore((s) => s.setResearchApiKey);
  const maxConcurrent = useSettingsStore((s) => s.researchMaxConcurrent);
  const setMaxConcurrent = useSettingsStore((s) => s.setResearchMaxConcurrent);

  return (
    <div className="flex flex-col gap-8">
      {/* 搜索提供商选择 */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="p-4 space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <Globe className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold">搜索提供商</h3>
          </div>
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              深度研究使用外部搜索服务获取最新资料。选择搜索提供商并配置对应的 API 密钥。
            </p>
            <Select value={searchProvider} onValueChange={(v) => setSearchProvider(v as any)}>
              <SelectTrigger size="sm" className="w-44">
                <SelectValue placeholder="选择提供商" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">不使用</SelectItem>
                <SelectItem value="tavily">Tavily</SelectItem>
                <SelectItem value="serpapi">SerpApi</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      {/* API 密钥 */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="p-4 space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <Key className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold">搜索 API 密钥</h3>
          </div>
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              所选搜索提供商对应的 API Key。Tavily 可在 tavily.com 获取，SerpApi 可在 serpapi.com 获取。
            </p>
            <Input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="输入搜索服务的 API 密钥"
              className="h-8 text-xs"
            />
          </div>
        </div>
      </div>

      {/* 最大并发任务数 */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="p-4 space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <ListOrdered className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold">最大并发任务</h3>
          </div>
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              同时进行的深度研究任务数量上限。并发越多速度越快，但 API 调用频率也越高。
            </p>
            <Select
              value={String(maxConcurrent)}
              onValueChange={(v) => setMaxConcurrent(Number(v))}
            >
              <SelectTrigger size="sm" className="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {[1, 2, 3, 4, 5].map((n) => (
                  <SelectItem key={n} value={String(n)}>
                    {n} 个任务
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>
    </div>
  );
}
