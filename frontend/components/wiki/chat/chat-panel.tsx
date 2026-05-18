'use client';

/**
 * 聊天主界面组件
 *
 * Wiki 知识库对话的核心容器，整合侧边栏、消息列表和输入框。
 * 移植自 llm_wiki 0.4.8 ChatPanel，适配 Gitter 设计风格。
 *
 * 布局结构：
 * ┌──────────┬──────────────────────────────┐
 * │ 侧边栏    │  消息区域                      │
 * │ (对话列表) │  - 可编辑标题                  │
 * │          │  - 消息列表 (ScrollArea)        │
 * │          │  - 输入框 (ChatInput)           │
 * └──────────┴──────────────────────────────┘
 *
 * 功能特性：
 * - 流式消息逐字展示（streamingContent）
 * - 自动滚动到底部
 * - 空状态提示："开始对话，探索项目知识"
 * - 停止生成 / 重新生成
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import { MessageSquare, Pencil, Check, X } from 'lucide-react';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { useChatStore } from '@/stores/chat-store';
import { useSettingsStore } from '@/lib/store/settings';
import { ChatMessage, StreamingMessage } from './chat-message';
import { ChatInput } from './chat-input';
import { ConversationSidebar } from './conversation-sidebar';

export function ChatPanel() {
  // ── 聊天状态 ──
  const activeConversationId = useChatStore((s) => s.activeConversationId);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const streamingContent = useChatStore((s) => s.streamingContent);
  const addMessage = useChatStore((s) => s.addMessage);
  const setStreaming = useChatStore((s) => s.setStreaming);
  const appendStreamToken = useChatStore((s) => s.appendStreamToken);
  const finalizeStream = useChatStore((s) => s.finalizeStream);
  const createConversation = useChatStore((s) => s.createConversation);
  const removeLastAssistantMessage = useChatStore((s) => s.removeLastAssistantMessage);
  const renameConversation = useChatStore((s) => s.renameConversation);
  const conversations = useChatStore((s) => s.conversations);

  // ── LLM 配置（统一从 settings-store 读取，与系统设置页面一致） ──
  const providerId = useSettingsStore((s) => s.providerId);
  const modelId = useSettingsStore((s) => s.modelId);
  const providersConfig = useSettingsStore((s) => s.providersConfig);
  const currentProvider = providersConfig[providerId];
  const apiKey = currentProvider?.apiKey || '';
  const baseUrl = currentProvider?.baseUrl || currentProvider?.defaultBaseUrl || '';

  // ── 向量检索配置（统一从 settings-store 读取） ──
  const wikiVectorEnabled = useSettingsStore((s) => s.wikiVectorEnabled);
  const wikiEmbeddingModel = useSettingsStore((s) => s.wikiEmbeddingModel);
  const wikiEmbeddingEndpoint = useSettingsStore((s) => s.wikiEmbeddingEndpoint);
  const wikiEmbeddingApiKey = useSettingsStore((s) => s.wikiEmbeddingApiKey);

  // ── 派生状态：当前活跃对话的消息 ──
  const allMessages = useChatStore((s) => s.messages);
  const activeMessages = activeConversationId
    ? allMessages.filter((m) => m.conversationId === activeConversationId)
    : [];

  // ── DOM 引用 ──
  const abortRef = useRef<AbortController | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // ── 标题编辑状态 ──
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState('');

  /** 当前活跃对话对象 */
  const activeConversation = conversations.find(
    (c) => c.id === activeConversationId,
  );

  // ── 自动滚动到底部 ──

  /** 是否已首次渲染完成（避免加载历史消息时触发页面级滚动） */
  const hasMountedRef = useRef(false);

  /**
   * 消息列表或流式内容更新时自动滚动到底部
   * 首次渲染使用 instant 模式避免页面偏移，后续使用 smooth
   */
  useEffect(() => {
    // 首次加载时用 instant 避免触发页面级滚动偏移
    const behavior = hasMountedRef.current ? 'smooth' : 'instant';
    messagesEndRef.current?.scrollIntoView({ behavior, block: 'end' });
    hasMountedRef.current = true;
  }, [activeMessages, streamingContent]);

  // ── 发送消息处理 ──

  /**
   * 发送消息并触发 LLM 流式调用
   *
   * @param text - 用户输入文本
   */
  const handleSend = useCallback(
    async (text: string) => {
      // 自动创建对话（如果无活跃对话）
      let convId = useChatStore.getState().activeConversationId;
      if (!convId) {
        convId = await createConversation();
      }

      addMessage('user', text);
      setStreaming(true);

      // 构建 LLM 请求消息
      const llmMessages = [
        {
          role: 'system' as const,
          content: '你是一个 Wiki 知识助手，帮助用户探索项目文档。请根据你的知识回答用户问题，保持回答简洁清晰。',
        },
        ...useChatStore
          .getState()
          .getActiveMessages()
          .filter((m) => m.role === 'user' || m.role === 'assistant')
          .slice(-10)
          .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content })),
      ];

      const controller = new AbortController();
      abortRef.current = controller;

      // accumulated 声明在 try 外部，确保 catch 中可访问
      let accumulated = '';
      // 路由来源引擎（来自 route 事件的 sources 字段）
      let routeSources: string[] = [];
      // 来源文件路径列表（来自 sources 事件的 sources 字段）
      let sourceFilePaths: string[] = [];

      try {
        // 调用 Wiki 智能路由查询接口（SSE 流式）
        const response = await fetch('/api/wiki/query', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            question: text,
            providerId,
            modelId,
            apiKey,
            baseUrl,
            vectorEnabled: wikiVectorEnabled || undefined,
            embeddingModel: wikiEmbeddingModel || undefined,
            embeddingEndpoint: wikiEmbeddingEndpoint || undefined,
            embeddingApiKey: wikiEmbeddingApiKey || undefined,
          }),
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`API 请求失败: ${response.status}`);
        }

        // 读取 SSE 流式响应
        const reader = response.body?.getReader();
        if (!reader) throw new Error('无法读取响应流');

        const decoder = new TextDecoder();

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const chunk = decoder.decode(value, { stream: true });
          const lines = chunk.split('\n');

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const data = line.slice(6);
              if (data === '[DONE]') continue;
              try {
                const parsed = JSON.parse(data);

                // 处理 route 事件：提取路由来源引擎
                if (parsed.type === 'route' && Array.isArray(parsed.sources)) {
                  routeSources = parsed.sources;
                }

                // 处理 sources 事件：提取来源引擎与引用文件路径
                if (parsed.type === 'sources') {
                  // engines 字段为实际使用的引擎列表，合并到 routeSources（优先使用实际引擎）
                  if (Array.isArray(parsed.engines) && parsed.engines.length > 0) {
                    routeSources = parsed.engines;
                  }
                  // sources 字段为引用的文件路径列表
                  if (Array.isArray(parsed.sources)) {
                    sourceFilePaths = parsed.sources;
                  }
                }

                // 处理 content 事件（后端 query 端点使用 type:'content' 格式逐字输出）
                if (parsed.type === 'content' && parsed.content) {
                  accumulated += parsed.content;
                  appendStreamToken(parsed.content);
                }

                // 兼容处理 LLM token 事件（OpenAI 兼容格式）
                const token = parsed.choices?.[0]?.delta?.content ?? '';
                if (token) {
                  accumulated += token;
                  appendStreamToken(token);
                }
              } catch {
                // 非 JSON 行，跳过
              }
            }
          }
        }

        finalizeStream(accumulated, undefined, routeSources, sourceFilePaths);
      } catch (err: unknown) {
        if ((err as Error).name === 'AbortError') {
          finalizeStream(accumulated || '生成已取消', undefined, routeSources, sourceFilePaths);
        } else {
          finalizeStream(`错误: ${(err as Error).message}`);
        }
      } finally {
        abortRef.current = null;
      }
    },
    [
      providerId,
      modelId,
      apiKey,
      baseUrl,
      wikiVectorEnabled,
      wikiEmbeddingModel,
      wikiEmbeddingEndpoint,
      wikiEmbeddingApiKey,
      addMessage,
      setStreaming,
      appendStreamToken,
      finalizeStream,
      createConversation,
    ],
  );

  /** 停止生成 */
  const handleStop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  /** 重新生成最后一条回复 */
  const handleRegenerate = useCallback(async () => {
    if (isStreaming) return;
    const active = useChatStore.getState().getActiveMessages();
    const lastUserMsg = [...active].reverse().find((m) => m.role === 'user');
    if (!lastUserMsg) return;

    removeLastAssistantMessage();
    await new Promise((r) => setTimeout(r, 50));

    // 移除原始用户消息（handleSend 会重新添加）
    useChatStore.setState((s) => ({
      messages: s.messages.filter((m) => m.id !== lastUserMsg.id),
    }));
    handleSend(lastUserMsg.content);
  }, [isStreaming, removeLastAssistantMessage, handleSend]);

  // ── 标题编辑处理 ──

  /** 开始编辑标题 */
  const startEditingTitle = () => {
    if (!activeConversation) return;
    setTitleDraft(activeConversation.title);
    setEditingTitle(true);
  };

  /** 确认标题修改 */
  const confirmTitleEdit = () => {
    if (activeConversationId && titleDraft.trim()) {
      renameConversation(activeConversationId, titleDraft.trim());
    }
    setEditingTitle(false);
  };

  /** 取消标题编辑 */
  const cancelTitleEdit = () => {
    setEditingTitle(false);
  };

  return (
    <div className="flex h-full flex-row overflow-hidden">
      {/* 左侧：对话列表侧边栏 */}
      <ConversationSidebar />

      {/* 右侧：聊天主区域 */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {!activeConversationId ? (
          // ── 空状态 ──
          <div className="flex flex-1 items-center justify-center text-muted-foreground">
            <div className="text-center">
              <MessageSquare className="mx-auto mb-3 h-8 w-8 opacity-30" />
              <p className="text-sm">开始对话，探索项目知识</p>
              <p className="mt-1 text-xs opacity-60">
                点击左侧"新建对话"开始
              </p>
            </div>
          </div>
        ) : (
          <>
            {/* 顶部标题栏（可编辑） */}
            <div className="flex items-center gap-2 border-b px-3 py-2 shrink-0">
              {editingTitle ? (
                <>
                  <input
                    type="text"
                    value={titleDraft}
                    onChange={(e) => setTitleDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') confirmTitleEdit();
                      if (e.key === 'Escape') cancelTitleEdit();
                    }}
                    className="flex-1 rounded border bg-background px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                    autoFocus
                  />
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    onClick={confirmTitleEdit}
                    title="确认"
                  >
                    <Check className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    onClick={cancelTitleEdit}
                    title="取消"
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </>
              ) : (
                <>
                  <h2 className="flex-1 text-sm font-medium truncate">
                    {activeConversation?.title ?? '新对话'}
                  </h2>
                  <button
                    onClick={startEditingTitle}
                    className="rounded p-1 text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                    title="编辑标题"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                </>
              )}
            </div>

            <Separator className="shrink-0" />

            {/* 中间：消息列表 */}
            <ScrollArea className="flex-1 min-h-0">
              <div className="flex flex-col gap-3 px-3 py-2">
                {activeMessages.map((msg, idx) => {
                  // 判断是否为最后一条助手消息
                  const isLastAssistant =
                    msg.role === 'assistant' &&
                    !activeMessages
                      .slice(idx + 1)
                      .some((m) => m.role === 'assistant');

                  return (
                    <ChatMessage
                      key={msg.id}
                      message={msg}
                      isLastAssistant={isLastAssistant && !isStreaming}
                      onRegenerate={isLastAssistant ? handleRegenerate : undefined}
                    />
                  );
                })}

                {/* 流式消息 */}
                {isStreaming && (
                  <StreamingMessage content={streamingContent} />
                )}

                {/* 滚动锚点 */}
                <div ref={messagesEndRef} />
              </div>
            </ScrollArea>
          </>
        )}

        {/* 底部：输入框（固定在底部，不会被挤压） */}
        <div className="shrink-0">
          <ChatInput
            onSend={handleSend}
            onStop={handleStop}
            isStreaming={isStreaming}
            placeholder="输入消息..."
          />
        </div>
      </div>
    </div>
  );
}
