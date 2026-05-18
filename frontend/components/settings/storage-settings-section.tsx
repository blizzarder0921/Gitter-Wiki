'use client';

/**
 * 存储设置面板 -- storage-settings-section.tsx
 *
 * 提供 Wiki 知识库存储相关的配置：
 * - 向量索引本地存储路径
 * - 对话历史保留策略
 * - 版本归档自动清理
 *
 * 依赖：
 *   - @/lib/store/settings：全局设置状态管理
 */

import { Database, MessageSquare, Archive } from 'lucide-react';
import { useSettingsStore } from '@/lib/store/settings';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';

export function StorageSettings() {
  const vectorPath = useSettingsStore((s) => s.storageVectorPath);
  const setVectorPath = useSettingsStore((s) => s.setStorageVectorPath);
  const chatRetention = useSettingsStore((s) => s.storageChatRetention);
  const setChatRetention = useSettingsStore((s) => s.setStorageChatRetention);
  const autoCleanup = useSettingsStore((s) => s.storageAutoCleanup);
  const setAutoCleanup = useSettingsStore((s) => s.setStorageAutoCleanup);

  return (
    <div className="flex flex-col gap-8">
      {/* 向量索引存储路径 */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="p-4 space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <Database className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold">向量索引存储</h3>
          </div>
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              sqlite-vec 向量索引文件的存储路径。留空则使用项目默认路径。
            </p>
            <Input
              value={vectorPath}
              onChange={(e) => setVectorPath(e.target.value)}
              placeholder="留空使用默认路径"
              className="h-8 text-xs"
            />
          </div>
        </div>
      </div>

      {/* 对话历史保留 */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="p-4 space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <MessageSquare className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold">对话历史保留</h3>
          </div>
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              超过保留期限的 Wiki 对话记录将被自动清除。选择永久保留则不会自动删除。
            </p>
            <Select value={chatRetention} onValueChange={(v) => setChatRetention(v as any)}>
              <SelectTrigger size="sm" className="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="30d">30 天</SelectItem>
                <SelectItem value="90d">90 天</SelectItem>
                <SelectItem value="forever">永久保留</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      {/* 自动清理旧版本 */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="p-4 space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <Archive className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold">自动清理旧版本</h3>
          </div>
          <div className="flex items-center justify-between gap-4">
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium">自动清理过期版本归档</p>
              <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
                开启后，超过保留期限的旧版本压缩包将被自动删除，以释放磁盘空间。
              </p>
            </div>
            <Switch
              checked={autoCleanup}
              onCheckedChange={setAutoCleanup}
              className="shrink-0"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
