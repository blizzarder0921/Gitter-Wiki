'use client';

/**
 * 聊天输入框组件
 *
 * 提供多行文本输入区域，支持 Enter 发送 / Shift+Enter 换行。
 * 流式接收中显示"停止生成"按钮，输入为空时发送按钮禁用。
 * 设计风格与 Gitter 首页输入框统一（圆角卡片样式）。
 *
 * 移植自 llm_wiki 0.4.8 ChatInput，适配 Gitter 项目架构。
 */

import { useRef, useState, useCallback } from 'react';
import { ArrowUp, Square, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

/** ChatInput 组件属性 */
interface ChatInputProps {
  /** 发送消息回调 */
  onSend: (text: string) => void;
  /** 停止生成回调 */
  onStop: () => void;
  /** 是否正在流式接收 */
  isStreaming: boolean;
  /** 输入框占位文本 */
  placeholder?: string;
}

/**
 * 聊天输入框
 *
 * - 多行输入（textarea），自动调整高度（最大 120px）
 * - Enter 发送，Shift+Enter 换行
 * - 流式接收中显示停止按钮
 * - 输入为空时发送按钮禁用
 */
export function ChatInput({
  onSend,
  onStop,
  isStreaming,
  placeholder,
}: ChatInputProps) {
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  /**
   * 处理输入变化，自动调整 textarea 高度
   *
   * 高度自适应内容，上限 120px 后出现滚动条。
   */
  const handleInput = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      setValue(e.target.value);
      const ta = e.target;
      ta.style.height = 'auto';
      ta.style.height = `${Math.min(ta.scrollHeight, 120)}px`;
    },
    [],
  );

  /**
   * 发送消息
   *
   * 对输入内容去前后空格后发送，发送后清空输入框并重置高度。
   */
  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || isStreaming) return;
    onSend(trimmed);
    setValue('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [value, isStreaming, onSend]);

  /**
   * 键盘事件处理
   *
   * Enter（不含 Shift）触发发送，Shift+Enter 插入换行。
   * 兼容 IME 输入法组合状态（中文输入时不触发发送）。
   */
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      // IME 组合中不触发发送（如中文拼音输入法选词阶段）
      if (e.nativeEvent.isComposing) return;
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  return (
    <div className="flex items-end gap-2 border-t p-3">
      {/* 多行输入区域 */}
      <textarea
        ref={textareaRef}
        value={value}
        dir="auto"
        onChange={handleInput}
        onKeyDown={handleKeyDown}
        placeholder={
          placeholder ??
          '输入消息...（Enter 发送，Shift+Enter 换行）'
        }
        disabled={isStreaming}
        rows={1}
        className={cn(
          'flex-1 resize-none rounded-lg border bg-background px-3 py-2 text-sm',
          'placeholder:text-muted-foreground',
          'focus:outline-none focus:ring-1 focus:ring-ring',
          'disabled:cursor-not-allowed disabled:opacity-50',
        )}
        style={{ maxHeight: '120px', overflowY: 'auto' }}
      />

      {/* 右侧按钮：流式中 -> 停止按钮；空闲时 -> 发送按钮 */}
      {isStreaming ? (
        <Button
          variant="destructive"
          size="icon"
          onClick={onStop}
          className="shrink-0 rounded-lg"
          title="停止生成"
        >
          <Square className="h-4 w-4" />
        </Button>
      ) : (
        <Button
          size="icon"
          onClick={handleSend}
          disabled={!value.trim()}
          className="shrink-0 rounded-lg"
          title="发送消息"
        >
          <ArrowUp className="h-4 w-4" />
        </Button>
      )}
    </div>
  );
}
