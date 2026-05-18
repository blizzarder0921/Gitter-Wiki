'use client';

/**
 * 自动进化设置面板 -- evolution-settings-section.tsx
 *
 * 提供 Wiki 知识库自动进化引擎的配置选项：
 * - Git 变更后自动触发增量摄入
 * - 定时 Lint 扫描频率
 * - 概念过时检测
 * - 跨项目关联分析
 *
 * 依赖：
 *   - @/lib/store/settings：全局设置状态管理
 */

import { GitBranch, Clock, AlertCircle, GitMerge } from 'lucide-react';
import { useSettingsStore } from '@/lib/store/settings';
import { Switch } from '@/components/ui/switch';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

export function EvolutionSettings() {
  const gitAutoIngest = useSettingsStore((s) => s.evolutionGitAutoIngest);
  const setGitAutoIngest = useSettingsStore((s) => s.setEvolutionGitAutoIngest);
  const lintSchedule = useSettingsStore((s) => s.evolutionLintSchedule);
  const setLintSchedule = useSettingsStore((s) => s.setEvolutionLintSchedule);
  const stalenessCheck = useSettingsStore((s) => s.evolutionStalenessCheck);
  const setStalenessCheck = useSettingsStore((s) => s.setEvolutionStalenessCheck);
  const crossProject = useSettingsStore((s) => s.evolutionCrossProject);
  const setCrossProject = useSettingsStore((s) => s.setEvolutionCrossProject);

  return (
    <div className="flex flex-col gap-8">
      {/* Git 变更自动摄入 */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="p-4 space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <GitBranch className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold">Git 变更自动摄入</h3>
          </div>
          <div className="flex items-center justify-between gap-4">
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium">变更文件自动更新 Wiki</p>
              <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
                Git pull 或本地修改后，自动检测变更文件并触发增量知识摄入。
              </p>
            </div>
            <Switch
              checked={gitAutoIngest}
              onCheckedChange={setGitAutoIngest}
              className="shrink-0"
            />
          </div>
        </div>
      </div>

      {/* 定时 Lint 扫描 */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="p-4 space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <Clock className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold">定时 Lint 扫描</h3>
          </div>
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              定期对 Wiki 页面执行结构与语义检查，发现孤立页面、失效链接和语义问题。
            </p>
            <Select value={lintSchedule} onValueChange={(v) => setLintSchedule(v as any)}>
              <SelectTrigger size="sm" className="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="daily">每天</SelectItem>
                <SelectItem value="weekly">每周</SelectItem>
                <SelectItem value="off">关闭</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      {/* 概念过时检测 */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="p-4 space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <AlertCircle className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold">概念过时检测</h3>
          </div>
          <div className="flex items-center justify-between gap-4">
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium">检测并标记过时知识</p>
              <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
                定期扫描技术概念，利用 LLM 判断知识是否已过时，建议更新相关页面。
              </p>
            </div>
            <Switch
              checked={stalenessCheck}
              onCheckedChange={setStalenessCheck}
              className="shrink-0"
            />
          </div>
        </div>
      </div>

      {/* 跨项目关联分析 */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="p-4 space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <GitMerge className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold">跨项目关联分析</h3>
          </div>
          <div className="flex items-center justify-between gap-4">
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium">发现跨项目知识关联</p>
              <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
                自动发现多个项目间的概念关联，生成跨项目对比页面和知识聚合。
              </p>
            </div>
            <Switch
              checked={crossProject}
              onCheckedChange={setCrossProject}
              className="shrink-0"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
