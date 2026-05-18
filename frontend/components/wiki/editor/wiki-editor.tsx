'use client';

/**
 * Wiki 页面编辑器组件
 *
 * 提供 Markdown 编辑与预览功能，支持保存到文件系统。
 * 接收 filePath 参数加载文件内容，通过 /api/wiki-fs POST 写入。
 *
 * 功能特性：
 * - 大文本框编辑 Markdown 内容
 * - 编辑 / 预览模式切换
 * - 保存按钮（调用 /api/wiki-fs）
 * - 文件加载状态与错误处理
 */

import { useState, useEffect, useCallback } from 'react';
import { Save, Eye, Pencil, Loader2, AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { WikiReader } from './wiki-reader';

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------

/** WikiEditor 组件属性 */
interface WikiEditorProps {
  /** 要编辑的文件路径（相对路径或绝对路径） */
  filePath: string
  /** 项目 ID（用于 API 调用上下文） */
  projectId?: number
  /** 保存成功回调 */
  onSave?: (filePath: string) => void
  /** 内容变更回调 */
  onChange?: (content: string) => void
}

// ---------------------------------------------------------------------------
// 组件
// ---------------------------------------------------------------------------

/**
 * Wiki 页面编辑器
 *
 * 支持编辑和预览两种模式：
 * - 编辑模式：textarea 大文本编辑
 * - 预览模式：使用 WikiReader 渲染 Markdown
 *
 * 通过 /api/wiki-fs 接口读写文件。
 */
export function WikiEditor({
  filePath,
  projectId,
  onSave,
  onChange,
}: WikiEditorProps) {
  /** 编辑模式：edit 编辑、preview 预览 */
  const [mode, setMode] = useState<'edit' | 'preview'>('edit');
  /** Markdown 内容 */
  const [content, setContent] = useState('');
  /** 原始内容（用于检测是否有未保存修改） */
  const [originalContent, setOriginalContent] = useState('');
  /** 加载状态 */
  const [loading, setLoading] = useState(false);
  /** 保存状态 */
  const [saving, setSaving] = useState(false);
  /** 错误信息 */
  const [error, setError] = useState<string | null>(null);
  /** 保存成功提示 */
  const [saveSuccess, setSaveSuccess] = useState(false);

  // ── 加载文件内容 ──

  /**
   * 从 API 加载文件内容
   *
   * 通过 /api/wiki-fs GET 接口读取指定文件。
   */
  const loadFile = useCallback(async () => {
    if (!filePath) return;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ path: filePath });
      if (projectId) params.set('projectId', String(projectId));

      const res = await fetch(`/api/wiki-fs?${params.toString()}`);
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `加载文件失败: ${res.status}`);
      }
      const data = await res.json();
      const fileContent = data.content ?? '';
      setContent(fileContent);
      setOriginalContent(fileContent);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [filePath, projectId]);

  // 文件路径变化时重新加载
  useEffect(() => {
    loadFile();
  }, [loadFile]);

  // ── 保存文件 ──

  /**
   * 将当前内容保存到文件系统
   *
   * 通过 /api/wiki-fs POST 接口写入文件。
   */
  const handleSave = useCallback(async () => {
    setSaving(true);
    setError(null);
    setSaveSuccess(false);
    try {
      const res = await fetch('/api/wiki-fs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: filePath,
          content,
          projectId,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `保存失败: ${res.status}`);
      }
      setOriginalContent(content);
      setSaveSuccess(true);
      onSave?.(filePath);
      // 3 秒后清除成功提示
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }, [content, filePath, projectId, onSave]);

  // ── 内容变更处理 ──

  /** 内容变更时同步更新本地状态并通知父组件 */
  const handleContentChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newContent = e.target.value;
    setContent(newContent);
    onChange?.(newContent);
  };

  /** 是否有未保存的修改 */
  const hasChanges = content !== originalContent;

  // ── 渲染 ──

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin mr-2" />
        加载文件中...
      </div>
    );
  }

  if (error && !content) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-muted-foreground">
        <AlertCircle className="h-8 w-8 text-destructive/60" />
        <p className="text-sm">{error}</p>
        <Button variant="outline" size="sm" onClick={loadFile}>
          重试
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* 工具栏 */}
      <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
        {/* 左侧：文件名 */}
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm font-medium truncate text-muted-foreground">
            {filePath.split(/[/\\]/).pop()}
          </span>
          {hasChanges && (
            <span className="text-[10px] text-yellow-600 dark:text-yellow-400 shrink-0">
              未保存
            </span>
          )}
        </div>

        {/* 右侧：操作按钮 */}
        <div className="flex items-center gap-1">
          {/* 模式切换 */}
          <div className="flex rounded-md border border-border bg-muted/30 p-0.5">
            <button
              onClick={() => setMode('edit')}
              className={cn(
                'flex items-center gap-1 rounded px-2.5 py-1 text-xs font-medium transition-colors',
                mode === 'edit'
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              <Pencil className="h-3 w-3" />
              编辑
            </button>
            <button
              onClick={() => setMode('preview')}
              className={cn(
                'flex items-center gap-1 rounded px-2.5 py-1 text-xs font-medium transition-colors',
                mode === 'preview'
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              <Eye className="h-3 w-3" />
              预览
            </button>
          </div>

          {/* 保存按钮 */}
          <Button
            size="sm"
            variant={hasChanges ? 'default' : 'outline'}
            onClick={handleSave}
            disabled={saving || !hasChanges}
            className="gap-1.5"
          >
            {saving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
            {saveSuccess ? '已保存!' : saving ? '保存中...' : '保存'}
          </Button>
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="flex items-center gap-2 mx-3 mt-2 px-3 py-2 rounded-md bg-destructive/10 text-destructive text-xs">
          <AlertCircle className="h-3.5 w-3.5 shrink-0" />
          <span>{error}</span>
          <button
            onClick={() => setError(null)}
            className="ml-auto text-destructive/70 hover:text-destructive"
          >
            关闭
          </button>
        </div>
      )}

      {/* 编辑/预览区域 */}
      <div className="flex-1 min-h-0">
        {mode === 'edit' ? (
          <textarea
            value={content}
            onChange={handleContentChange}
            className="w-full h-full resize-none border-0 bg-transparent px-4 py-3 font-mono text-sm leading-relaxed focus:outline-none placeholder:text-muted-foreground/50"
            placeholder="在此输入 Markdown 内容..."
            spellCheck={false}
          />
        ) : (
          <WikiReader content={content} />
        )}
      </div>

      {/* 底部状态栏 */}
      <div className="flex items-center justify-between border-t px-3 py-1.5 text-[10px] text-muted-foreground">
        <span>{content.length} 字符</span>
        <span>{content.split(/\n/).length} 行</span>
      </div>
    </div>
  );
}
