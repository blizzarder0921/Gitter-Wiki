'use client';

/**
 * 文件预览组件
 *
 * 根据文件路径从 API 加载内容，展示文件名和 Markdown 渲染结果。
 * 支持不同类型的文件分类展示。
 *
 * 功能特性：
 * - 接收 filePath，自动从全局 Wiki 加载文件内容
 * - 文件名展示 + 标签分类
 * - Markdown 内容渲染（react-markdown）
 * - 加载状态、错误状态、空状态处理
 */

import { useEffect, useState, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import rehypeRaw from 'rehype-raw';
import { rehypeStripReactIgnoredAttrs } from '@/lib/utils/rehype-strip-attrs';
import 'katex/dist/katex.min.css';
import {
  FileText,
  Image,
  Film,
  Music,
  FileSpreadsheet,
  FileQuestion,
  Loader2,
  AlertCircle,
  Code,
} from 'lucide-react';
import { cn } from '@/lib/utils';

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------

/** 文件分类 */
type FileCategory =
  | 'image'
  | 'video'
  | 'audio'
  | 'pdf'
  | 'code'
  | 'data'
  | 'text'
  | 'markdown'
  | 'document'
  | 'unknown';

/** FilePreview 组件属性 */
interface FilePreviewProps {
  /** 文件路径 */
  filePath: string
  /** 文件加载成功回调 */
  onLoaded?: (content: string) => void
}

// ---------------------------------------------------------------------------
// 工具函数
// ---------------------------------------------------------------------------

/**
 * 根据文件扩展名判断文件分类
 *
 * @param filePath - 文件路径
 * @returns 文件分类
 */
function getFileCategory(filePath: string): FileCategory {
  const ext = filePath.split('.').pop()?.toLowerCase() ?? '';

  // 图片
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'bmp', 'ico'].includes(ext))
    return 'image';
  // 视频
  if (['mp4', 'webm', 'ogv', 'mov', 'avi', 'mkv'].includes(ext))
    return 'video';
  // 音频
  if (['mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a'].includes(ext))
    return 'audio';
  // 代码
  if (
    ['ts', 'tsx', 'js', 'jsx', 'py', 'rs', 'go', 'java', 'c', 'cpp', 'h', 'css', 'html', 'vue', 'svelte', 'json', 'xml', 'yaml', 'yml', 'toml'].includes(ext)
  )
    return 'code';
  // 数据
  if (['csv', 'tsv', 'sql', 'sqlite', 'db'].includes(ext))
    return 'data';
  // Markdown
  if (['md', 'mdx', 'markdown'].includes(ext)) return 'markdown';
  // 文档
  if (['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'].includes(ext))
    return 'document';
  // 文本
  if (['txt', 'log', 'env', 'gitignore', 'editorconfig', 'cfg', 'ini'].includes(ext))
    return 'text';

  return 'unknown';
}

/**
 * 获取文件名的显示部分（从路径中提取）
 *
 * @param filePath - 文件完整路径
 * @returns 文件名
 */
function getFileName(filePath: string): string {
  const parts = filePath.replace(/\\/g, '/').split('/');
  return parts[parts.length - 1] || filePath;
}

// ---------------------------------------------------------------------------
// 分类标签配置
// ---------------------------------------------------------------------------

/** 各文件分类的显示配置 */
const CATEGORY_CONFIG: Record<
  FileCategory,
  { icon: typeof FileText; label: string; color: string }
> = {
  image: { icon: Image, label: '图片', color: 'text-green-500' },
  video: { icon: Film, label: '视频', color: 'text-blue-500' },
  audio: { icon: Music, label: '音频', color: 'text-purple-500' },
  pdf: { icon: FileText, label: 'PDF', color: 'text-red-500' },
  code: { icon: Code, label: '代码', color: 'text-orange-500' },
  data: { icon: FileSpreadsheet, label: '数据', color: 'text-teal-500' },
  text: { icon: FileText, label: '文本', color: 'text-gray-500' },
  markdown: { icon: FileText, label: 'Markdown', color: 'text-blue-500' },
  document: {
    icon: FileSpreadsheet,
    label: '文档',
    color: 'text-yellow-500',
  },
  unknown: { icon: FileQuestion, label: '未知', color: 'text-gray-400' },
};

// ---------------------------------------------------------------------------
// 组件
// ---------------------------------------------------------------------------

/**
 * 文件预览组件
 *
 * 加载文件内容并根据分类展示：
 * - Markdown / 文本 / 代码：使用 react-markdown 或纯文本渲染
 * - 图片 / 视频 / 音频：显示媒体标签
 * - 不可预览类型：显示占位提示
 */
export function FilePreview({ filePath, onLoaded }: FilePreviewProps) {
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const category = getFileCategory(filePath);
  const fileName = getFileName(filePath);
  const config = CATEGORY_CONFIG[category];

  // ── 加载文件内容 ──

  /**
   * 从 API 加载文件内容
   */
  useEffect(() => {
    if (!filePath) return;
    setLoading(true);
    setError(null);

    const params = new URLSearchParams({ path: filePath });

    fetch(`/api/wiki-fs?${params.toString()}`)
      .then(async (res) => {
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          // FastAPI 422 的 detail 是数组对象，需提取可读消息
          let detail = data.detail;
          if (Array.isArray(detail)) {
            detail = detail.map((e: { msg?: string }) => e.msg || String(e)).join('; ');
          }
          throw new Error(detail || `加载文件失败: ${res.status}`);
        }
        return res.json();
      })
      .then((data) => {
        const fileContent = data.content ?? '';
        setContent(fileContent);
        onLoaded?.(fileContent);
      })
      .catch((err) => {
        setError((err as Error).message);
      })
      .finally(() => {
        setLoading(false);
      });
  }, [filePath, onLoaded]);

  // ── 渲染 ──

  /** 是否为可渲染为 Markdown 的类型 */
  const isMarkdownRenderable =
    category === 'markdown' || category === 'text' || category === 'code';

  /** 是否为媒体类型（图片/视频/音频） */
  const isMedia =
    category === 'image' || category === 'video' || category === 'audio';

  /** 是否完全不可预览 */
  const isUnsupported =
    category === 'document' || (category === 'unknown' && !content);

  // 加载中
  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin mr-2" />
        加载文件中...
      </div>
    );
  }

  // 加载错误
  if (error && !content) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-muted-foreground">
        <AlertCircle className="h-8 w-8 text-destructive/60" />
        <p className="text-sm">{error}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-auto">
      {/* 文件信息栏 */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b bg-muted/20">
        <config.icon className={cn('h-4 w-4 shrink-0', config.color)} />
        <span className="text-sm font-medium truncate">{fileName}</span>
        <span
          className={cn(
            'rounded px-1.5 py-0.5 text-[10px] font-medium',
            'bg-muted/50',
            config.color,
          )}
        >
          {config.label}
        </span>
        {content && (
          <span className="ml-auto text-[10px] text-muted-foreground">
            {content.length.toLocaleString()} 字符
          </span>
        )}
      </div>

      {/* 内容区域 */}
      <div className="flex-1 overflow-auto p-4">
        {!content ? (
          <div className="flex items-center justify-center h-full text-sm text-muted-foreground">
            暂无内容
          </div>
        ) : isUnsupported ? (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
            <config.icon className="h-12 w-12 opacity-30" />
            <p className="text-sm">此文件类型暂不支持预览</p>
            <p className="text-xs opacity-60">{filePath}</p>
          </div>
        ) : isMarkdownRenderable ? (
          <div className="prose prose-sm max-w-none dark:prose-invert prose-p:my-1.5 prose-headings:my-3 prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5 prose-pre:my-3 prose-code:text-xs prose-code:before:content-none prose-code:after:content-none">
            <ReactMarkdown
              remarkPlugins={[remarkGfm, remarkMath]}
              rehypePlugins={[rehypeRaw, rehypeKatex, rehypeStripReactIgnoredAttrs]}
              components={{
                table: ({ children, ...props }) => (
                  <div className="my-2 overflow-x-auto rounded border border-border">
                    <table
                      className="w-full border-collapse text-xs"
                      {...props}
                    >
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
                    className="border border-border/80 bg-muted px-3 py-1.5 text-start font-semibold"
                    {...props}
                  >
                    {children}
                  </th>
                ),
                td: ({ children, ...props }) => (
                  <td
                    className="border border-border/60 px-3 py-1.5"
                    {...props}
                  >
                    {children}
                  </td>
                ),
                pre: ({ children, ...props }) => (
                  <pre
                    dir="ltr"
                    className="rounded bg-background/50 p-2.5 text-xs overflow-x-auto"
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
              {content}
            </ReactMarkdown>
          </div>
        ) : (
          <pre className="whitespace-pre-wrap font-mono text-sm leading-relaxed text-foreground/80">
            {content}
          </pre>
        )}
      </div>
    </div>
  );
}
