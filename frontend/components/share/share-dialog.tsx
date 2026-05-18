'use client';

/**
 * 分享文案生成弹窗组件
 *
 * 提供项目分享文案的完整生成流程：
 * 1. 风格选择 - 5 种预设风格卡片（技术评测/种草推荐/新闻速递/教程指南/极客简报）
 * 2. 文案生成 - 调用 LLM API 生成 Markdown 文案和配图提示词
 * 3. 文案展示 - 预览（Markdown 渲染）/ 编辑（Textarea）双模式切换
 * 4. 配图提示词 - 独立可编辑区域
 * 5. 导出功能 - 复制 Markdown / 复制富文本 / 下载 .md / 重新生成
 *
 * 依赖模块：
 * - @/components/ui/dialog, button, textarea, tabs
 * - @/lib/store/settings (useSettingsStore)
 * - @/lib/db/projects (Project 类型)
 * - react-markdown, remark-gfm, lucide-react, sonner
 */

import { useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { rehypeStripReactIgnoredAttrs } from '@/lib/utils/rehype-strip-attrs';
import {
  Microscope,
  Heart,
  Zap,
  BookOpen,
  Terminal,
  Loader2,
  Copy,
  ClipboardCopy,
  Download,
  RefreshCw,
} from 'lucide-react';
import { toast } from 'sonner';

import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useSettingsStore } from '@/lib/store/settings';
import { type Project } from '@/lib/types';

// ---------------------------------------------------------------------------
// 预设风格定义
// ---------------------------------------------------------------------------

/** 风格卡片配置项 */
interface ShareStyleItem {
  /** 风格唯一标识，对应 API 的 style 参数 */
  value: string;
  /** 风格显示名称 */
  label: string;
  /** 风格简短描述 */
  desc: string;
  /** 风格图标组件 */
  icon: React.ComponentType<{ className?: string }>;
}

/** 5 种预设分享文案风格 */
const SHARE_STYLES: ShareStyleItem[] = [
  { value: 'tech-review', label: '技术评测', desc: '深度分析架构与优劣势', icon: Microscope },
  { value: 'recommend', label: '种草推荐', desc: '热情推荐亮点突出', icon: Heart },
  { value: 'news-flash', label: '新闻速递', desc: '简洁客观核心信息', icon: Zap },
  { value: 'tutorial', label: '教程指南', desc: '入门友好步骤清晰', icon: BookOpen },
  { value: 'geek-brief', label: '极客简报', desc: '极简风格核心数据', icon: Terminal },
];

// ---------------------------------------------------------------------------
// 组件属性接口
// ---------------------------------------------------------------------------

/** ShareDialog 组件属性 */
interface ShareDialogProps {
  /** 弹窗是否打开 */
  open: boolean;
  /** 弹窗打开状态变更回调 */
  onOpenChange: (open: boolean) => void;
  /** 当前项目信息 */
  project: Project;
}

// ---------------------------------------------------------------------------
// 辅助函数：简单 Markdown → HTML 转换
// ---------------------------------------------------------------------------

/**
 * 将 Markdown 文本转换为简易 HTML
 *
 * 支持的语法：标题（h1-h3）、粗体、斜体、链接、行内代码、
 * 代码块、无序列表、有序列表、段落分隔。
 * 注意：此函数仅用于"复制富文本"场景，不做完整 Markdown 解析。
 *
 * @param md - Markdown 原始文本
 * @returns 转换后的 HTML 字符串
 */
function simpleMarkdownToHtml(md: string): string {
  let html = md;

  /** 代码块：```lang\n...\n``` → <pre><code>...</code></pre> */
  html = html.replace(/```[\w]*\n([\s\S]*?)```/g, (_match, code: string) => {
    const escaped = code
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
    return `<pre style="background:#f6f8fa;padding:12px;border-radius:6px;overflow-x:auto;"><code>${escaped}</code></pre>`;
  });

  /** 标题 h3 → h1 依次处理 */
  html = html.replace(/^### (.+)$/gm, '<h3 style="font-size:1.1em;font-weight:600;margin:16px 0 8px;">$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2 style="font-size:1.25em;font-weight:600;margin:20px 0 10px;">$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1 style="font-size:1.5em;font-weight:700;margin:24px 0 12px;">$1</h1>');

  /** 粗体 */
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

  /** 斜体 */
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

  /** 链接 */
  html = html.replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2" style="color:#0969da;text-decoration:underline;">$1</a>');

  /** 行内代码 */
  html = html.replace(/`([^`]+)`/g, '<code style="background:#f6f8fa;padding:2px 6px;border-radius:4px;font-size:0.9em;">$1</code>');

  /** 无序列表 */
  html = html.replace(/^[-*] (.+)$/gm, '<li style="margin-left:20px;list-style:disc;">$1</li>');

  /** 有序列表 */
  html = html.replace(/^\d+\. (.+)$/gm, '<li style="margin-left:20px;list-style:decimal;">$1</li>');

  /** 水平分割线 */
  html = html.replace(/^---$/gm, '<hr style="border:none;border-top:1px solid #d0d7de;margin:16px 0;" />');

  /** 段落：连续空行分段 */
  html = html.replace(/\n{2,}/g, '</p><p style="margin:8px 0;">');

  /** 单换行 → <br> */
  html = html.replace(/\n/g, '<br>');

  /** 包裹在段落标签中 */
  html = `<p style="margin:8px 0;">${html}</p>`;

  return html;
}

// ---------------------------------------------------------------------------
// 主组件
// ---------------------------------------------------------------------------

/**
 * 分享文案生成弹窗
 *
 * 状态流转：
 *   初始（风格选择） → 生成中（loading） → 生成完成（文案展示）
 *   生成完成时风格选择区折叠，点击"重新生成"回到风格选择。
 *
 * @param props - ShareDialogProps
 */
export default function ShareDialog({
  open,
  onOpenChange,
  project,
}: ShareDialogProps) {
  /** 当前选中的风格 ID（默认使用用户设置的默认风格） */
  const [selectedStyle, setSelectedStyle] = useState<string>('tech-review');
  /** 是否正在生成文案 */
  const [generating, setGenerating] = useState(false);
  /** 是否已生成文案（控制风格选择区折叠/展开） */
  const [generated, setGenerated] = useState(false);
  /** 生成的文案内容（Markdown 格式） */
  const [content, setContent] = useState('');
  /** 配图提示词 */
  const [imagePrompt, setImagePrompt] = useState('');
  /** 编辑模式下的文案内容 */
  const [editContent, setEditContent] = useState('');

  /** 从全局设置中获取 LLM 配置 */
  const { providerId, modelId, providersConfig, shareDefaultStyle, shareAgentPrompt } = useSettingsStore();

  /** 当前提供商的 API 密钥和端点地址（baseUrl 为空时回退到 defaultBaseUrl） */
  const currentProvider = providersConfig[providerId];
  const apiKey = currentProvider?.apiKey ?? '';
  const baseUrl = currentProvider?.baseUrl || currentProvider?.defaultBaseUrl || '';

  // -------------------------------------------------------------------------
  // 文案生成
  // -------------------------------------------------------------------------

  /**
   * 调用后端 API 生成分享文案
   *
   * 请求体包含项目 ID、风格、模型配置等信息，
   * 响应返回 { content, imagePrompt }。
   */
  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    setGenerated(false);

    try {
      const response = await fetch('/api/share/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          projectId: project.id,
          style: selectedStyle,
          agentPrompt: shareAgentPrompt,
          providerId,
          modelId,
          apiKey,
          baseUrl,
        }),
      });

      const result = await response.json();

      /** 接口返回非 200 状态码时提示错误 */
      if (!response.ok) {
        const errMsg = result.detail || result.message || '文案生成失败';
        toast.error(errMsg);
        return;
      }

      if (result.code !== 200) {
        toast.error(result.message || result.detail || '文案生成失败');
        return;
      }

      /** 更新文案内容和配图提示词 */
      const { content: genContent, imagePrompt: genImagePrompt } = result.data;
      setContent(genContent);
      setEditContent(genContent);
      setImagePrompt(genImagePrompt);
      setGenerated(true);
    } catch (error) {
      const msg = error instanceof Error ? error.message : '网络请求失败';
      toast.error(`文案生成失败：${msg}`);
    } finally {
      setGenerating(false);
    }
  }, [project.id, selectedStyle, shareAgentPrompt, providerId, modelId, apiKey, baseUrl]);

  // -------------------------------------------------------------------------
  // 重新生成：回到风格选择界面
  // -------------------------------------------------------------------------

  /** 重置生成状态，回到风格选择步骤 */
  const handleRegenerate = useCallback(() => {
    setGenerated(false);
    setContent('');
    setEditContent('');
    setImagePrompt('');
  }, []);

  // -------------------------------------------------------------------------
  // 导出功能
  // -------------------------------------------------------------------------

  /** 复制 Markdown 纯文本到剪贴板 */
  const handleCopyMarkdown = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(content);
      toast.success('Markdown 已复制到剪贴板');
    } catch {
      toast.error('复制失败，请手动复制');
    }
  }, [content]);

  /**
   * 复制富文本（HTML）到剪贴板
   *
   * 使用 ClipboardItem API 同时写入 text/html 和 text/plain，
   * 粘贴到富文本编辑器时保留格式，粘贴到纯文本编辑器时降级为 Markdown。
   */
  const handleCopyRichText = useCallback(async () => {
    try {
      const htmlContent = `<meta charset="utf-8"><div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height: 1.6; max-width: 800px; margin: 0 auto; padding: 20px;">${simpleMarkdownToHtml(content)}</div>`;
      const blob = new Blob([htmlContent], { type: 'text/html' });
      const textBlob = new Blob([content], { type: 'text/plain' });
      await navigator.clipboard.write([
        new ClipboardItem({ 'text/html': blob, 'text/plain': textBlob }),
      ]);
      toast.success('富文本已复制到剪贴板');
    } catch {
      toast.error('复制富文本失败，浏览器可能不支持此功能');
    }
  }, [content]);

  /**
   * 下载文案为 .md 文件
   *
   * 使用 Blob + URL.createObjectURL 创建临时下载链接，
   * 下载完成后释放 URL 对象。
   */
  const handleDownload = useCallback(() => {
    const fileName = `${project.name}-分享文案.md`;
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    toast.success('文件下载已开始');
  }, [content, project.name]);

  // -------------------------------------------------------------------------
  // 弹窗关闭时重置状态
  // -------------------------------------------------------------------------

  /** 弹窗打开状态变更处理：关闭时重置内部状态 */
  const handleOpenChange = useCallback(
    (newOpen: boolean) => {
      if (!newOpen) {
        /** 关闭弹窗时重置所有状态 */
        setGenerated(false);
        setContent('');
        setEditContent('');
        setImagePrompt('');
        setGenerating(false);
        setSelectedStyle(shareDefaultStyle || 'tech-review');
      }
      onOpenChange(newOpen);
    },
    [onOpenChange, shareDefaultStyle],
  );

  // -------------------------------------------------------------------------
  // 渲染
  // -------------------------------------------------------------------------

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        {/* 弹窗标题与描述 */}
        <DialogTitle>生成分享文案</DialogTitle>
        <DialogDescription>
          为「{project.name}」选择文案风格，AI 将自动生成分享文案和配图提示词
        </DialogDescription>

        {/* ===== 风格选择区域：生成后折叠 ===== */}
        {!generated && (
          <div className="space-y-4">
            {/* 风格卡片网格 */}
            <div className="grid grid-cols-2 gap-3">
              {SHARE_STYLES.map((style) => {
                const Icon = style.icon;
                const isSelected = selectedStyle === style.value;
                return (
                  <button
                    key={style.value}
                    type="button"
                    onClick={() => setSelectedStyle(style.value)}
                    className={`
                      flex items-start gap-3 rounded-lg border p-3 text-left transition-all
                      hover:bg-muted/50 cursor-pointer
                      ${isSelected
                        ? 'border-primary bg-primary/5 ring-1 ring-primary/30'
                        : 'border-border'
                      }
                    `}
                    aria-pressed={isSelected}
                    aria-label={`选择${style.label}风格`}
                  >
                    {/* 风格图标 */}
                    <Icon className={`size-5 shrink-0 mt-0.5 ${isSelected ? 'text-primary' : 'text-muted-foreground'}`} />
                    {/* 风格名称与描述 */}
                    <div className="min-w-0">
                      <div className={`text-sm font-medium ${isSelected ? 'text-primary' : ''}`}>
                        {style.label}
                      </div>
                      <div className="text-xs text-muted-foreground mt-0.5">
                        {style.desc}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>

            {/* 生成按钮 */}
            <Button
              onClick={handleGenerate}
              disabled={generating}
              className="w-full"
              size="lg"
            >
              {generating ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  正在生成文案...
                </>
              ) : (
                '生成文案'
              )}
            </Button>
          </div>
        )}

        {/* ===== 生成中 Loading 状态 ===== */}
        {generating && (
          <div className="flex flex-col items-center justify-center py-12 gap-3">
            <Loader2 className="size-8 animate-spin text-primary" />
            <p className="text-sm text-muted-foreground">
              AI 正在撰写文案，请稍候...
            </p>
          </div>
        )}

        {/* ===== 文案展示区域：生成完成后展开 ===== */}
        {generated && !generating && (
          <div className="space-y-4">
            {/* 当前风格标签 + 重新生成按钮 */}
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                当前风格：{SHARE_STYLES.find((s) => s.value === selectedStyle)?.label ?? selectedStyle}
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleRegenerate}
                aria-label="重新选择风格"
              >
                <RefreshCw className="size-3.5" />
                重新生成
              </Button>
            </div>

            {/* 文案预览/编辑切换 */}
            <Tabs defaultValue="preview">
              <TabsList>
                <TabsTrigger value="preview">预览</TabsTrigger>
                <TabsTrigger value="edit">编辑</TabsTrigger>
              </TabsList>

              {/* 预览模式：Markdown 渲染 */}
              <TabsContent value="preview">
                <div className="rounded-lg border bg-muted/30 p-4 max-h-[40vh] overflow-y-auto">
                  <div className="prose prose-sm max-w-none dark:prose-invert">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw, rehypeStripReactIgnoredAttrs]}>
                      {content}
                    </ReactMarkdown>
                  </div>
                </div>
              </TabsContent>

              {/* 编辑模式：Textarea 可修改 */}
              <TabsContent value="edit">
                <Textarea
                  value={editContent}
                  onChange={(e) => {
                    setEditContent(e.target.value);
                    setContent(e.target.value);
                  }}
                  className="min-h-[200px] max-h-[40vh] font-mono text-sm"
                  placeholder="编辑文案内容..."
                  aria-label="编辑文案内容"
                />
              </TabsContent>
            </Tabs>

            {/* 配图提示词区域 */}
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="image-prompt">
                配图提示词
              </label>
              <Textarea
                id="image-prompt"
                value={imagePrompt}
                onChange={(e) => setImagePrompt(e.target.value)}
                className="min-h-[80px] font-mono text-sm"
                placeholder="配图提示词将在此显示，可手动编辑..."
                aria-label="编辑配图提示词"
              />
            </div>

            {/* 导出按钮组 */}
            <div className="flex flex-wrap gap-2">
              {/* 复制 Markdown */}
              <Button variant="outline" size="sm" onClick={handleCopyMarkdown}>
                <Copy className="size-3.5" />
                复制 Markdown
              </Button>

              {/* 复制富文本 */}
              <Button variant="outline" size="sm" onClick={handleCopyRichText}>
                <ClipboardCopy className="size-3.5" />
                复制富文本
              </Button>

              {/* 下载 .md 文件 */}
              <Button variant="outline" size="sm" onClick={handleDownload}>
                <Download className="size-3.5" />
                下载
              </Button>

              {/* 重新生成 */}
              <Button variant="outline" size="sm" onClick={handleRegenerate}>
                <RefreshCw className="size-3.5" />
                重新生成
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
