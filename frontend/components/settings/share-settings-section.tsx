'use client';

/**
 * 分享文案设置面板 -- share-settings-section.tsx
 *
 * 提供 Agent 角色提示词编辑和默认文案风格选择功能。
 * 用户可自定义分享时 Agent 扮演的角色与语气，并选择默认的文案输出风格。
 * 设置数据通过 useSettingsStore 持久化至 SQLite。
 *
 * 依赖：
 *   - @/lib/store/settings：全局设置状态管理
 *   - @/components/ui/textarea：多行文本输入组件
 *   - @/components/ui/select：下拉选择器组件
 *   - @/components/ui/button：按钮组件
 *   - lucide-react：图标库
 */

import { FileText, Palette, RotateCcw } from 'lucide-react';
import { useSettingsStore } from '@/lib/store/settings';
import { DEFAULT_SHARE_AGENT_PROMPT } from '@/lib/store/settings';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Button } from '@/components/ui/button';

// ---------------------------------------------------------------------------
// 常量定义
// ---------------------------------------------------------------------------

/** 文案风格选项：value 对应 store 中的 shareDefaultStyle，label 为展示文本，desc 为描述 */
const SHARE_STYLES = [
  { value: 'tech-review', label: '技术评测', desc: '深度分析技术架构、优劣势' },
  { value: 'recommend', label: '种草推荐', desc: '热情推荐、亮点突出' },
  { value: 'news-flash', label: '新闻速递', desc: '简洁客观、核心信息' },
  { value: 'tutorial', label: '教程指南', desc: '入门友好、步骤清晰' },
  { value: 'geek-brief', label: '极客简报', desc: '极简风格、核心数据' },
] as const;

// ---------------------------------------------------------------------------
// 主组件
// ---------------------------------------------------------------------------

/**
 * 分享文案设置面板
 *
 * 布局与 WikiSettingsSection 保持一致：每个设置项使用独立的圆角卡片，
 * 包含图标标题区、描述文字和交互控件三部分。
 */
export function ShareSettingsSection() {
  /** Agent 角色提示词 */
  const shareAgentPrompt = useSettingsStore((state) => state.shareAgentPrompt);
  const setShareAgentPrompt = useSettingsStore((state) => state.setShareAgentPrompt);

  /** 默认文案风格 */
  const shareDefaultStyle = useSettingsStore((state) => state.shareDefaultStyle);
  const setShareDefaultStyle = useSettingsStore((state) => state.setShareDefaultStyle);

  /**
   * 恢复 Agent 角色提示词为默认值
   * 将 store 中的 shareAgentPrompt 重置为 DEFAULT_SHARE_AGENT_PROMPT
   */
  const handleResetPrompt = () => {
    setShareAgentPrompt(DEFAULT_SHARE_AGENT_PROMPT);
  };

  return (
    <div className="flex flex-col gap-8">
      {/* Agent 角色提示词编辑 */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="p-4 space-y-4">
          {/* 标题区 */}
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <FileText className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold">Agent 角色提示词</h3>
          </div>

          {/* 描述与编辑区 */}
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              定义分享文案生成时 Agent 扮演的角色与语气。提示词越具体，生成的文案越贴合预期。
            </p>
            <Textarea
              value={shareAgentPrompt}
              onChange={(e) => setShareAgentPrompt(e.target.value)}
              placeholder="请输入 Agent 角色提示词..."
              className="min-h-[200px] text-xs resize-y leading-relaxed"
            />
            <div className="flex items-center justify-between">
              <p className="text-[11px] text-muted-foreground">
                支持多行输入，建议包含角色定位、输出要求和格式说明
              </p>
              {/* 恢复默认按钮 */}
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 gap-1.5 text-xs text-muted-foreground hover:text-foreground"
                onClick={handleResetPrompt}
                aria-label="恢复默认提示词"
              >
                <RotateCcw className="w-3 h-3" />
                恢复默认
              </Button>
            </div>
          </div>
        </div>
      </div>

      {/* 默认文案风格选择 */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="p-4 space-y-4">
          {/* 标题区 */}
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <Palette className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold">默认文案风格</h3>
          </div>

          {/* 描述与选择器 */}
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              选择生成分享文案时使用的默认风格，可在生成时临时切换。
            </p>
            <Select
              value={shareDefaultStyle}
              onValueChange={(val) => setShareDefaultStyle(val)}
            >
              <SelectTrigger size="sm" className="w-56">
                <SelectValue placeholder="选择文案风格" />
              </SelectTrigger>
              <SelectContent>
                {SHARE_STYLES.map((style) => (
                  <SelectItem key={style.value} value={style.value}>
                    <span className="flex items-center gap-2">
                      <span>{style.label}</span>
                      <span className="text-muted-foreground">- {style.desc}</span>
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {/* 当前风格说明 */}
            <p className="text-[11px] text-muted-foreground">
              {SHARE_STYLES.find((s) => s.value === shareDefaultStyle)?.desc ?? '选择一种风格查看说明'}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
