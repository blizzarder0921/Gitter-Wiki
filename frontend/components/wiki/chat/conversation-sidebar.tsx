'use client';

/**
 * 对话列表侧边栏组件
 *
 * 展示所有对话的列表，支持创建、切换和删除。
 * 适配全局 Wiki 架构，所有 API 调用无需 projectId。
 *
 * 功能特性：
 * - 新建对话按钮（Plus 图标）
 * - 对话列表（标题 + 时间 + 消息数）
 * - 当前活跃对话高亮（primary 主题色）
 * - 悬浮删除按钮（Trash2 图标），带确认提示
 * - 启动时自动从后端加载对话列表
 * - 点击对话卡片加载历史消息
 */

import { useEffect, useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useChatStore } from '@/stores/chat-store';
import { cn } from '@/lib/utils';

/**
 * 格式化时间戳为可读日期
 *
 * 当天消息显示时间（HH:MM），非当天显示月/日。
 *
 * @param timestamp - Unix 毫秒时间戳
 * @returns 格式化后的日期字符串
 */
function formatDate(timestamp: number): string {
  const d = new Date(timestamp);
  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();
  if (isToday) {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

export function ConversationSidebar() {
  // ── 从 chat-store 获取状态 ──
  const conversations = useChatStore((s) => s.conversations);
  const activeConversationId = useChatStore((s) => s.activeConversationId);
  const messages = useChatStore((s) => s.messages);
  const createConversation = useChatStore((s) => s.createConversation);
  const deleteConversation = useChatStore((s) => s.deleteConversation);
  const setActiveConversation = useChatStore((s) => s.setActiveConversation);
  const loadConversations = useChatStore((s) => s.loadConversations);

  /** 当前悬浮的对话 ID（用于显示删除按钮） */
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  /** 正在删除的对话 ID（防止重复点击） */
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // 启动时从后端加载对话列表
  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  // 按更新时间降序排列对话列表
  const sorted = [...conversations].sort((a, b) => b.updatedAt - a.updatedAt);

  /**
   * 获取指定对话的消息数量
   *
   * @param convId - 对话 ID
   * @returns 该对话下的消息总数
   */
  function getMessageCount(convId: string): number {
    return messages.filter((m) => m.conversationId === convId).length;
  }

  /** 处理新建对话 */
  const handleCreate = async () => {
    await createConversation();
  };

  /** 处理切换对话（从后端加载消息） */
  const handleSelect = async (id: string) => {
    await setActiveConversation(id);
  };

  /** 处理删除对话 */
  const handleDelete = async (id: string) => {
    setDeletingId(id);
    try {
      await deleteConversation(id);
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="flex h-full w-[200px] flex-shrink-0 flex-col border-r bg-muted/30">
      {/* 顶部：新建对话按钮 */}
      <div className="border-b p-2">
        <Button
          variant="outline"
          size="sm"
          className="w-full gap-2"
          onClick={handleCreate}
        >
          <Plus className="h-3.5 w-3.5" />
          新建对话
        </Button>
      </div>

      {/* 中间：对话列表 */}
      <div className="flex-1 min-h-0 overflow-y-auto py-1">
        {sorted.length === 0 ? (
          <p className="px-3 py-4 text-xs text-muted-foreground text-center">
            暂无对话
          </p>
        ) : (
          sorted.map((conv) => {
            const isActive = conv.id === activeConversationId;
            const msgCount = getMessageCount(conv.id);
            const isDeleting = deletingId === conv.id;
            return (
              <div
                key={conv.id}
                className={cn(
                  'group relative mx-1 my-0.5 flex cursor-pointer flex-col rounded-md px-2 py-1.5 text-sm transition-colors',
                  isActive
                    ? 'bg-primary/10 text-primary'
                    : 'hover:bg-accent text-foreground',
                  isDeleting && 'opacity-50 pointer-events-none',
                )}
                onClick={() => handleSelect(conv.id)}
                onMouseEnter={() => setHoveredId(conv.id)}
                onMouseLeave={() => setHoveredId(null)}
              >
                {/* 标题行 + 悬浮删除按钮 */}
                <div className="flex items-start justify-between gap-1">
                  <span className="line-clamp-2 flex-1 text-xs font-medium leading-snug">
                    {conv.title}
                  </span>
                  {hoveredId === conv.id && !isDeleting && (
                    <button
                      className="flex-shrink-0 rounded p-0.5 text-muted-foreground hover:text-destructive transition-colors"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (confirm('确定删除此对话？')) {
                          handleDelete(conv.id);
                        }
                      }}
                      title="删除对话"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  )}
                </div>

                {/* 时间 & 消息数 */}
                <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-muted-foreground">
                  <span>{formatDate(conv.updatedAt)}</span>
                  {msgCount > 0 && (
                    <>
                      <span>·</span>
                      <span>{msgCount} 条消息</span>
                    </>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
