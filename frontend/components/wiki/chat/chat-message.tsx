'use client';

/**
 * 聊天消息组件
 *
 * 渲染单条聊天消息，支持 Markdown、KaTeX 数学公式、
 * 思维链折叠、引用来源列表等功能。
 *
 * 移植自 llm_wiki 0.4.8 ChatMessage / StreamingMessage，
 * 适配 Gitter 项目架构（Tailwind CSS + shadcn/ui + lucide-react）。
 *
 * 功能特性：
 * - 用户消息：右对齐，紫色主题背景
 * - 助手消息：左对齐，灰色背景
 * - Markdown 渲染（react-markdown + remark-gfm）
 * - KaTeX 数学公式（remark-math + rehype-katex）
 * - 思维链折叠检测（<think> 标签）
 * - 引用来源列表（references）
 * - 流式消息展示
 * - 消息复制按钮
 */

import { useCallback, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import rehypeRaw from 'rehype-raw';
import { rehypeStripReactIgnoredAttrs } from '@/lib/utils/rehype-strip-attrs';
import 'katex/dist/katex.min.css';
import {
  Bot,
  User,
  ChevronDown,
  ChevronRight,
  Copy,
  Check,
  FileText,
  Search,
  BookOpen,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import type { DisplayMessage } from '@/stores/chat-store';

// ---------------------------------------------------------------------------
// 导出组件
// ---------------------------------------------------------------------------

/** ChatMessage 组件属性 */
interface ChatMessageProps {
  /** 消息数据 */
  message: DisplayMessage
  /** 是否为最后一条助手消息（展示重新生成按钮） */
  isLastAssistant?: boolean
  /** 重新生成回调 */
  onRegenerate?: () => void
}

/**
 * 单条聊天消息
 *
 * 根据角色区分样式：
 * - user：右对齐，紫色（primary）背景
 * - assistant：左对齐，灰色（muted）背景，支持 Markdown
 * - system：居中，弱化样式
 */
export function ChatMessage({ message, isLastAssistant, onRegenerate }: ChatMessageProps) {
  const isUser = message.role === 'user';
  const isAssistant = message.role === 'assistant';
  const [hovered, setHovered] = useState(false);

  return (
    <div
      className={cn('flex gap-2', isUser ? 'flex-row-reverse' : 'flex-row')}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* 头像 */}
      <div
        className={cn(
          'flex h-7 w-7 shrink-0 items-center justify-center rounded-full',
          isUser
            ? 'bg-primary text-primary-foreground'
            : 'bg-muted text-muted-foreground',
        )}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>

      {/* 消息内容 */}
      <div className="max-w-[80%] flex flex-col gap-1.5">
        <div
          className={cn(
            'rounded-lg px-3 py-2 text-sm',
            isUser
              ? 'bg-primary text-primary-foreground'
              : 'bg-muted text-foreground',
          )}
        >
          {isUser ? (
            <p dir="auto" className="whitespace-pre-wrap break-words">
              {message.content}
            </p>
          ) : (
            <MarkdownContent content={message.content} />
          )}
        </div>

        {/* 引用来源面板（仅助手消息） */}
        {isAssistant && message.references && message.references.length > 0 && (
          <CitedReferencesPanel references={message.references} />
        )}

        {/* 来源引擎标记（仅助手消息） */}
        {isAssistant && message.answerSources && message.answerSources.length > 0 && (
          <SourceBadges sources={message.answerSources} />
        )}

        {/* 来源文件列表（仅助手消息） */}
        {isAssistant && message.sourceFiles && message.sourceFiles.length > 0 && (
          <SourceFilesPanel sourceFiles={message.sourceFiles} />
        )}

        {/* 悬浮操作按钮（invisible 方式保留空间，hover 时显示，不影响布局流） */}
        {isAssistant && (
          <div className={cn("flex items-center gap-1 h-5", !hovered && "invisible")}>
            <CopyButton content={message.content} />
            {isLastAssistant && onRegenerate && (
              <button
                type="button"
                onClick={onRegenerate}
                className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors"
                title="重新生成此回复"
              >
                重新生成
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 流式消息组件
// ---------------------------------------------------------------------------

/** StreamingMessage 组件属性 */
interface StreamingMessageProps {
  /** 流式累积内容 */
  content: string
}

/**
 * 流式消息展示组件
 *
 * 实时渲染 LLM 的流式输出，包含：
 * - 思维链区域（<think> 标签内，动画闪烁提示）
 * - 已完成的思维链（折叠显示）
 * - 回答正文（逐字输出 + 闪烁光标）
 */
export function StreamingMessage({ content }: StreamingMessageProps) {
  const { thinking, answer } = useMemo(() => separateThinking(content), [content]);
  const isThinking = thinking !== null && answer.length === 0;

  return (
    <div className="flex gap-2 flex-row">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <Bot className="h-4 w-4" />
      </div>
      <div className="max-w-[80%] rounded-lg px-3 py-2 text-sm bg-muted text-foreground">
        {isThinking ? (
          <StreamingThinkingBlock content={thinking} />
        ) : (
          <>
            {thinking && <ThinkingBlock content={thinking} />}
            <MarkdownContent content={answer} />
            <span className="animate-pulse">&#9607;</span>
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Markdown 渲染
// ---------------------------------------------------------------------------

/** MarkdownContent 组件属性 */
interface MarkdownContentProps {
  /** Markdown 原始内容 */
  content: string
}

/**
 * Markdown 内容渲染组件
 *
 * 支持 GitHub Flavored Markdown（GFM）和 KaTeX 数学公式。
 * 自动分离思维链（<think>）标签并折叠展示。
 */
function MarkdownContent({ content }: MarkdownContentProps) {
  // 去除 HTML 注释中的隐藏内容（如 <!-- cited: 1,3,5 -->）
  const cleaned = content.replace(/<!--[\s\S]*?-->/g, '').trimEnd();

  // 分离思维链与正文
  const { thinking, answer } = useMemo(() => separateThinking(cleaned), [cleaned]);
  // wikilink → markdown 链接转换
  const processed = useMemo(() => processContent(answer), [answer]);

  return (
    <div>
      {thinking && <ThinkingBlock content={thinking} />}
      <div className="chat-markdown prose prose-sm max-w-none dark:prose-invert prose-p:my-1 prose-headings:my-2 prose-ul:my-1 prose-ol:my-1 prose-li:my-0 prose-pre:my-2 prose-code:text-xs prose-code:before:content-none prose-code:after:content-none">
        <ReactMarkdown
          remarkPlugins={[remarkGfm, remarkMath]}
          rehypePlugins={[rehypeRaw, rehypeKatex, rehypeStripReactIgnoredAttrs]}
          components={{
            // 链接渲染
            a: ({ href, children }) => (
              <span
                className="text-primary underline cursor-default"
                title={href}
              >
                {children}
              </span>
            ),
            // 表格容器
            table: ({ children, ...props }) => (
              <div className="my-2 overflow-x-auto rounded border border-border">
                <table className="w-full border-collapse text-xs" {...props}>
                  {children}
                </table>
              </div>
            ),
            thead: ({ children, ...props }) => (
              <thead className="bg-muted" {...props}>
                {children}
              </thead>
            ),
            th: ({ children, ...props }) => (
              <th
                className="border border-border/80 px-3 py-1.5 text-start font-semibold bg-muted"
                {...props}
              >
                {children}
              </th>
            ),
            td: ({ children, ...props }) => (
              <td className="border border-border/60 px-3 py-1.5" {...props}>
                {children}
              </td>
            ),
            // 代码块
            pre: ({ children, ...props }) => (
              <pre
                dir="ltr"
                className="rounded bg-background/50 p-2 text-xs overflow-x-auto"
                style={{ textAlign: 'left' }}
                {...props}
              >
                {children}
              </pre>
            ),
            code: ({ className, children, ...props }) => (
              <code dir="ltr" className={className} {...props}>
                {children}
              </code>
            ),
          }}
        >
          {processed}
        </ReactMarkdown>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 思维链处理
// ---------------------------------------------------------------------------

/**
 * 分离思维链（<think>...</think>）与正文
 *
 * 处理完整的 <think> / <thinking> 标签对，以及流式中的未闭合标签。
 *
 * @param text - 原始消息文本
 * @returns 思维链内容（null 表示无）与正文内容
 */
function separateThinking(text: string): {
  thinking: string | null;
  answer: string;
} {
  const thinkRegex = /<think(?:ing)?>([\s\S]*?)<\/think(?:ing)?>/gi;
  const thinkParts: string[] = [];
  let answer = text;

  let match: RegExpExecArray | null;
  while ((match = thinkRegex.exec(text)) !== null) {
    thinkParts.push(match[1].trim());
  }
  answer = answer
    .replace(/<think(?:ing)?>[\s\S]*?<\/think(?:ing)?>/gi, '')
    .trim();

  // 处理未闭合的 <think> 标签（流式进行中）
  const unclosedMatch = answer.match(/<think(?:ing)?>([\s\S]*)$/i);
  if (unclosedMatch) {
    thinkParts.push(unclosedMatch[1].trim());
    answer = answer.replace(/<think(?:ing)?>[\s\S]*$/i, '').trim();
  }

  const thinking = thinkParts.length > 0 ? thinkParts.join('\n\n') : null;
  return { thinking, answer };
}

/**
 * 流式思维链展示（动画）
 *
 * 显示最近 5 行思维过程，带渐入动画和闪烁光标。
 */
function StreamingThinkingBlock({ content }: { content: string }) {
  const lines = content.split('\n').filter((l) => l.trim());
  const visibleLines = lines.slice(-5);

  return (
    <div className="rounded-md border border-dashed border-amber-500/30 bg-amber-50/50 dark:bg-amber-950/20 px-2.5 py-2">
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className="text-sm animate-pulse">&#x1F4AD;</span>
        <span className="text-xs font-medium text-amber-700 dark:text-amber-400">
          正在思考...
        </span>
        <span className="text-[10px] text-amber-600/50 dark:text-amber-500/40">
          {lines.length} 行
        </span>
      </div>
      <div className="h-[5lh] overflow-hidden text-xs text-amber-800/70 dark:text-amber-300/60 font-mono leading-relaxed">
        {visibleLines.map((line, i) => (
          <div
            key={lines.length - 5 + i}
            className="truncate"
            style={{ opacity: 0.4 + (i / visibleLines.length) * 0.6 }}
          >
            {line}
          </div>
        ))}
        <span className="animate-pulse text-amber-500">&#9607;</span>
      </div>
    </div>
  );
}

/**
 * 已完成思维链折叠面板
 *
 * 默认折叠，点击标题展开显示完整思维过程。
 */
function ThinkingBlock({ content }: { content: string }) {
  const [expanded, setExpanded] = useState(false);
  const lines = content.split('\n').filter((l) => l.trim());

  return (
    <div className="mb-2 rounded-md border border-dashed border-amber-500/30 bg-amber-50/50 dark:bg-amber-950/20">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-xs text-amber-700 dark:text-amber-400 hover:bg-amber-100/50 dark:hover:bg-amber-900/20 transition-colors rounded-t-md"
      >
        <span className="text-sm">&#x1F4AD;</span>
        <span className="font-medium">思考了 {lines.length} 行</span>
        <span className="text-amber-600/60 dark:text-amber-500/60 ml-auto">
          {expanded ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronRight className="h-3 w-3" />
          )}
        </span>
      </button>
      {expanded && (
        <div className="border-t border-amber-500/20 px-2.5 py-2 text-xs text-amber-800/80 dark:text-amber-300/70 whitespace-pre-wrap max-h-64 overflow-y-auto font-mono leading-relaxed">
          {content}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 内容处理
// ---------------------------------------------------------------------------

/**
 * 处理消息内容
 *
 * - 将独立的 \begin{...}...\end{...} 包裹为 $$...$$（KaTeX 公式块）
 * - 将 [[wikilink]] 转换为 Markdown 链接
 * - 修复不完整的 [[name] 格式
 *
 * @param text - 原始消息文本
 * @returns 处理后的文本
 */
function processContent(text: string): string {
  let result = text;

  // 包裹独立的 \begin{...}...\end{...} 公式块
  result = result.replace(
    /(?<!\$\$\s*)(\\begin\{[^}]+\}[\s\S]*?\\end\{[^}]+\})(?!\s*\$\$)/g,
    (_match, block: string) => `$$\n${block}\n$$`,
  );

  // 修复不完整的 [[name] 格式
  result = result.replace(/\[\[([^\]]+)\](?!\])/g, '[[$1]]');

  // 将 [[wikilinks]] 转换为 Markdown 链接
  result = result.replace(
    /\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]/g,
    (_match, pageName: string, displayText?: string) => {
      const display = displayText?.trim() || pageName.trim();
      return `[${display}](wikilink:${pageName.trim()})`;
    },
  );

  return result;
}

// ---------------------------------------------------------------------------
// 引用来源面板
// ---------------------------------------------------------------------------

/** CitedReferencesPanel 组件属性 */
interface CitedReferencesPanelProps {
  /** 引用来源列表 */
  references: { title: string; path: string }[]
}

/**
 * 引用来源面板
 *
 * 展示助手回复引用的 Wiki 页面列表，
 * 超过 3 条时默认折叠，可展开查看全部。
 */
function CitedReferencesPanel({ references }: CitedReferencesPanelProps) {
  const [expanded, setExpanded] = useState(false);

  const MAX_COLLAPSED = 3;
  const visibleRefs = expanded ? references : references.slice(0, MAX_COLLAPSED);
  const hasMore = references.length > MAX_COLLAPSED;

  return (
    <div className="rounded-md border border-border/60 bg-muted/30 text-xs mb-1">
      <button
        type="button"
        onClick={() => hasMore && setExpanded(!expanded)}
        className="flex w-full items-center gap-1.5 px-2 py-1 text-muted-foreground hover:text-foreground transition-colors"
      >
        <FileText className="h-3 w-3 shrink-0" />
        <span className="font-medium">引用来源 ({references.length})</span>
        {hasMore &&
          (expanded ? (
            <ChevronDown className="h-3 w-3 ml-auto" />
          ) : (
            <ChevronRight className="h-3 w-3 ml-auto" />
          ))}
      </button>
      <div className="px-2 pb-1.5">
        {visibleRefs.map((ref, i) => (
          <div
            key={ref.path}
            className="flex items-center gap-1.5 rounded px-1 py-0.5 text-left"
            title={ref.path}
          >
            <span className="text-[10px] text-muted-foreground/60 w-4 shrink-0 text-right">
              [{i + 1}]
            </span>
            <FileText className="h-3 w-3 shrink-0 text-muted-foreground" />
            <span className="truncate text-foreground/80">{ref.title}</span>
          </div>
        ))}
        {hasMore && !expanded && (
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="w-full text-center text-[10px] text-muted-foreground hover:text-primary pt-0.5"
          >
            +{references.length - MAX_COLLAPSED} 更多...
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 复制按钮
// ---------------------------------------------------------------------------

/**
 * 复制按钮组件
 *
 * 点击后将消息内容复制到剪贴板，
 * 复制前自动去除 HTML 注释与思维链标签。
 */
function CopyButton({ content }: { content: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    // 去除 HTML 注释和思维链标签
    const clean = content
      .replace(/<!--[\s\S]*?-->/g, '')
      .replace(/<think(?:ing)?>\s*[\s\S]*?<\/think(?:ing)?>\s*/gi, '')
      .replace(/<think(?:ing)?>\s*[\s\S]*$/gi, '')
      .trim();

    await navigator.clipboard.writeText(clean);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [content]);

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors"
      title="复制到剪贴板"
    >
      {copied ? (
        <Check className="h-3 w-3" />
      ) : (
        <Copy className="h-3 w-3" />
      )}
      {copied ? '已复制!' : '复制'}
    </button>
  );
}

// ---------------------------------------------------------------------------
// 来源引擎标记
// ---------------------------------------------------------------------------

/** SourceBadges 组件属性 */
interface SourceBadgesProps {
  /** 来源引擎列表，如 ["graphify", "wiki"] */
  sources: string[]
}

/**
 * 来源引擎标记组件
 *
 * 在 AI 回答底部显示答案来源标签：
 * - graphify → "代码图谱" 标签（带搜索图标）
 * - wiki → "知识库" 标签（带书本图标）
 * 标签使用小号、浅色样式，不干扰正文阅读。
 */
function SourceBadges({ sources }: SourceBadgesProps) {
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {sources.includes('graphify') && (
        <span className="inline-flex items-center gap-1 rounded-full border border-blue-500/20 bg-blue-500/10 px-2 py-0.5 text-[10px] text-blue-400 dark:text-blue-300">
          <Search className="h-2.5 w-2.5" />
          代码图谱
        </span>
      )}
      {sources.includes('wiki') && (
        <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-400 dark:text-emerald-300">
          <BookOpen className="h-2.5 w-2.5" />
          知识库
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 来源文件面板
// ---------------------------------------------------------------------------

/** SourceFilesPanel 组件属性 */
interface SourceFilesPanelProps {
  /** 引用的来源文件路径列表 */
  sourceFiles: string[]
}

/**
 * 来源文件面板组件
 *
 * 显示回答所引用的来源文件路径列表，
 * 超过 3 条时默认折叠，可展开查看全部。
 * 以小号、浅色样式展示，不干扰正文阅读。
 */
function SourceFilesPanel({ sourceFiles }: SourceFilesPanelProps) {
  const [expanded, setExpanded] = useState(false);

  const MAX_COLLAPSED = 3;
  const visibleFiles = expanded ? sourceFiles : sourceFiles.slice(0, MAX_COLLAPSED);
  const hasMore = sourceFiles.length > MAX_COLLAPSED;

  /** 从文件路径中提取文件名用于显示 */
  const getFileName = (path: string) => {
    const parts = path.split('/');
    return parts[parts.length - 1] || path;
  };

  return (
    <div className="rounded-md border border-border/40 bg-muted/20 text-xs">
      <button
        type="button"
        onClick={() => hasMore && setExpanded(!expanded)}
        className="flex w-full items-center gap-1.5 px-2 py-1 text-muted-foreground hover:text-foreground transition-colors"
      >
        <FileText className="h-3 w-3 shrink-0" />
        <span className="font-medium">引用文件 ({sourceFiles.length})</span>
        {hasMore &&
          (expanded ? (
            <ChevronDown className="h-3 w-3 ml-auto" />
          ) : (
            <ChevronRight className="h-3 w-3 ml-auto" />
          ))}
      </button>
      <div className="px-2 pb-1.5">
        {visibleFiles.map((file, i) => (
          <div
            key={file}
            className="flex items-center gap-1.5 rounded px-1 py-0.5 text-left"
            title={file}
          >
            <span className="text-[10px] text-muted-foreground/60 w-4 shrink-0 text-right">
              [{i + 1}]
            </span>
            <FileText className="h-2.5 w-2.5 shrink-0 text-muted-foreground/60" />
            <span className="truncate text-foreground/70">{getFileName(file)}</span>
          </div>
        ))}
        {hasMore && !expanded && (
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="w-full text-center text-[10px] text-muted-foreground hover:text-primary pt-0.5"
          >
            +{sourceFiles.length - MAX_COLLAPSED} 更多...
          </button>
        )}
      </div>
    </div>
  );
}
