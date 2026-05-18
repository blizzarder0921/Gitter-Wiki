'use client';

/**
 * Wiki 页面阅读器组件
 *
 * 以只读模式渲染 Markdown 内容，支持：
 * - GitHub Flavored Markdown（GFM）
 * - KaTeX 数学公式渲染
 * - wikilink [[page]] 语法检测与点击跳转
 * - Frontmatter 元数据展示（可选折叠面板）
 *
 * 移植自 llm_wiki 0.4.8 WikiReader，适配 Gitter 项目架构。
 */

import { useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import rehypeRaw from 'rehype-raw';
import { rehypeStripReactIgnoredAttrs } from '@/lib/utils/rehype-strip-attrs';
import 'katex/dist/katex.min.css';
import { ChevronDown, ChevronRight, FileText, Info } from 'lucide-react';
import { cn } from '@/lib/utils';

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------

/** Wiki 页面 frontmatter 元数据 */
interface FrontmatterData {
  /** 页面标题 */
  title?: string
  /** 页面类型 */
  type?: string
  /** 标签列表 */
  tags?: string[]
  /** 创建日期 */
  created?: string
  /** 更新时间 */
  updated?: string
  /** 其他自定义字段 */
  [key: string]: unknown
}

/** WikiReader 组件属性 */
interface WikiReaderProps {
  /** Markdown 原始内容 */
  content: string
  /** wikilink 点击回调（可选），传递目标页面名称 */
  onWikilinkClick?: (pageName: string) => void
}

// ---------------------------------------------------------------------------
// 工具函数
// ---------------------------------------------------------------------------

/**
 * 解析 Markdown frontmatter（YAML 格式的 --- 分隔块）
 *
 * 仅支持简单的 key: value 格式，不支持嵌套 YAML。
 *
 * @param text - 完整 Markdown 文本
 * @returns frontmatter 数据与正文分离结果
 */
function parseFrontmatter(text: string): {
  frontmatter: FrontmatterData | null
  body: string
} {
  const match = text.match(/^---\n([\s\S]*?)\n---\n?/);
  if (!match) return { frontmatter: null, body: text };

  const fmText = match[1];
  const body = text.slice(match[0].length);
  const data: FrontmatterData = {};

  // 逐行解析简单 key: value
  for (const line of fmText.split('\n')) {
    const colonIdx = line.indexOf(':');
    if (colonIdx === -1) continue;
    const key = line.slice(0, colonIdx).trim();
    let value = line.slice(colonIdx + 1).trim();

    // 去除引号包裹
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }

    // 解析数组（如 tags: [a, b, c]）
    if (value.startsWith('[') && value.endsWith(']')) {
      const inner = value.slice(1, -1);
      data[key] = inner
        .split(',')
        .map((s) => s.trim().replace(/^["']|["']$/g, ''));
    } else {
      data[key] = value;
    }
  }

  return { frontmatter: data, body };
}

/**
 * 将 wikilink [[page]] 语法转换为 Markdown 链接
 *
 * 保留原始 wikilink 标记以便前端拦截点击事件。
 *
 * @param text - 原始 Markdown 文本
 * @returns 转换后的文本
 */
function transformWikilinks(text: string): string {
  return text.replace(
    /\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]/g,
    (_match, pageName: string, displayText?: string) => {
      const display = displayText?.trim() || pageName.trim();
      // 使用特殊协议标记，由前端拦截
      return `[${display}](#wikilink:${encodeURIComponent(pageName.trim())})`;
    },
  );
}

// ---------------------------------------------------------------------------
// 组件
// ---------------------------------------------------------------------------

/**
 * Wiki 页面阅读器
 *
 * 接收 Markdown 内容字符串，渲染为格式化文档。
 * 自动解析 frontmatter 并以可折叠面板展示。
 */
export function WikiReader({ content, onWikilinkClick }: WikiReaderProps) {
  // 解析 frontmatter
  const { frontmatter, body } = useMemo(
    () => parseFrontmatter(content),
    [content],
  );

  // wikilink 转换
  const transformed = useMemo(() => transformWikilinks(body), [body]);

  /** frontmatter 折叠状态 */
  const [fmExpanded, setFmExpanded] = useState(true);

  /**
   * 处理链接点击
   *
   * 拦截 #wikilink:xxx 协议的点击，提取页面名称后回调。
   */
  function handleAnchorClick(
    e: React.MouseEvent<HTMLAnchorElement>,
    href: string,
  ) {
    if (href.startsWith('#wikilink:')) {
      e.preventDefault();
      const pageName = decodeURIComponent(href.slice('#wikilink:'.length));
      onWikilinkClick?.(pageName);
    }
  }

  // 提取 frontmatter 中可展示的字段
  const displayFields = frontmatter
    ? Object.entries(frontmatter).filter(
        ([key]) => !key.startsWith('_'), // 过滤私有字段
      )
    : [];

  return (
    <div className="flex flex-col h-full">
      {/* Frontmatter 面板 */}
      {frontmatter && displayFields.length > 0 && (
        <div className="border-b">
          <button
            type="button"
            onClick={() => setFmExpanded(!fmExpanded)}
            className="flex w-full items-center gap-1.5 px-4 py-2 text-xs text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
          >
            <Info className="h-3 w-3" />
            <span className="font-medium">页面信息</span>
            {fmExpanded ? (
              <ChevronDown className="h-3 w-3 ml-auto" />
            ) : (
              <ChevronRight className="h-3 w-3 ml-auto" />
            )}
          </button>
          {fmExpanded && (
            <div className="px-4 pb-2">
              <div className="rounded-md bg-muted/30 p-3">
                <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                  {displayFields.map(([key, value]) => (
                    <div key={key} className="flex items-baseline gap-2">
                      <span className="font-medium text-muted-foreground shrink-0">
                        {key}:
                      </span>
                      <span className="text-foreground truncate">
                        {Array.isArray(value)
                          ? value.join(', ')
                          : String(value)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Markdown 渲染区域 */}
      <div className="flex-1 overflow-auto p-4">
        <div className="prose prose-sm max-w-none dark:prose-invert prose-p:my-1.5 prose-headings:my-3 prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5 prose-pre:my-3 prose-code:text-xs prose-code:before:content-none prose-code:after:content-none">
          <ReactMarkdown
          remarkPlugins={[remarkGfm, remarkMath]}
          rehypePlugins={[rehypeRaw, rehypeKatex, rehypeStripReactIgnoredAttrs]}
            components={{
              // 链接渲染（拦截 wikilink）
              a: ({ href, children, ...props }) => {
                const h = typeof href === 'string' ? href : '';
                const isWikilink = h.startsWith('#wikilink:');
                return (
                  <a
                    href={h || undefined}
                    onClick={(e) =>
                      isWikilink && handleAnchorClick(e, h)
                    }
                    className={cn(
                      isWikilink
                        ? 'cursor-pointer text-primary underline decoration-primary/40 underline-offset-2 hover:decoration-primary'
                        : 'text-primary underline underline-offset-2',
                    )}
                    {...props}
                  >
                    {children}
                  </a>
                );
              },
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
                  className="border border-border/80 bg-muted px-3 py-1.5 text-start font-semibold"
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
              // 图片
              img: ({ src, alt, ...props }) => (
                <img
                  src={src}
                  alt={alt ?? ''}
                  className="max-w-full rounded border border-border/40"
                  loading="lazy"
                  {...props}
                />
              ),
            }}
          >
            {transformed}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  );
}
