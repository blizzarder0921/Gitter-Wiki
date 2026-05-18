/**
 * 聊天状态管理 (Zustand Store)
 *
 * 管理对话列表、消息流、流式响应状态。
 * 适配全局 Wiki 架构，所有 API 调用无需 projectId。
 *
 * 核心职责：
 * - 对话 CRUD（创建、删除、切换、重命名）— 自动持久化到后端
 * - 消息管理（添加用户/助手消息、流式追加 token、最终化流）— 自动保存到后端
 * - 流式状态控制（isStreaming / streamingContent）
 * - 启动时从后端加载对话列表
 */

import { create } from 'zustand'

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------

/** 对话记录，包含标识、标题与时间戳 */
export interface Conversation {
  /** 对话唯一标识（后端数据库 ID 的字符串形式） */
  id: string
  /** 对话标题（默认取首条用户消息前 50 字符） */
  title: string
  /** 创建时间（Unix 毫秒时间戳） */
  createdAt: number
  /** 最后更新时间（Unix 毫秒时间戳） */
  updatedAt: number
}

/** 消息引用，指向 Wiki 中的某个页面 */
export interface MessageReference {
  /** 被引用页面标题 */
  title: string
  /** 被引用页面相对路径 */
  path: string
}

/** 展示用消息，包含角色、内容、时间戳 */
export interface DisplayMessage {
  /** 消息唯一标识 */
  id: string
  /** 消息角色 */
  role: 'user' | 'assistant' | 'system'
  /** 消息文本内容 */
  content: string
  /** 发送时间（Unix 毫秒时间戳） */
  timestamp: number
  /** 所属对话 ID */
  conversationId: string
  /** 引用的 Wiki 页面列表（仅助手消息） */
  references?: MessageReference[]
  /** 答案来源引擎列表，如 ["graphify", "wiki"]（仅助手消息，来自 route 事件） */
  answerSources?: string[]
  /** 引用的来源文件路径列表（仅助手消息，来自 sources 事件） */
  sourceFiles?: string[]
}

// ---------------------------------------------------------------------------
// Store 状态与操作接口
// ---------------------------------------------------------------------------

interface ChatState {
  /** 所有对话列表 */
  conversations: Conversation[]
  /** 当前活跃对话 ID */
  activeConversationId: string | null
  /** 所有消息列表 */
  messages: DisplayMessage[]
  /** 是否正在流式接收助手回复 */
  isStreaming: boolean
  /** 流式接收中的累积内容 */
  streamingContent: string
  /** 聊天模式：chat 普通对话、ingest 摄入模式 */
  mode: 'chat' | 'ingest'
  /** 摄入源文件路径（ingest 模式专用） */
  ingestSource: string | null
  /** 最大历史消息数（控制上下文窗口） */
  maxHistoryMessages: number

  // ── 对话管理 ──

  /** 创建新对话并激活，返回新对话 ID（同时持久化到后端） */
  createConversation: () => Promise<string>
  /** 删除对话及其关联消息（同时删除后端数据），若为当前活跃则切换至下一个 */
  deleteConversation: (id: string) => Promise<void>
  /** 设置当前活跃对话（同时从后端加载该对话的消息） */
  setActiveConversation: (id: string | null) => Promise<void>
  /** 重命名对话标题（同时更新后端） */
  renameConversation: (id: string, title: string) => Promise<void>

  // ── 消息管理 ──

  /** 添加一条消息到当前对话（同时保存到后端） */
  addMessage: (role: DisplayMessage['role'], content: string, extra?: { answerSources?: string[]; sourceFiles?: string[] }) => Promise<void>
  /** 批量替换消息列表 */
  setMessages: (messages: DisplayMessage[]) => void
  /** 批量替换对话列表 */
  setConversations: (conversations: Conversation[]) => void
  /** 设置流式状态 */
  setStreaming: (streaming: boolean) => void
  /** 追加流式 token */
  appendStreamToken: (token: string) => void
  /** 最终化流式内容为完整助手消息（同时保存到后端） */
  finalizeStream: (content: string, references?: MessageReference[], answerSources?: string[], sourceFiles?: string[]) => Promise<void>
  /** 设置聊天模式 */
  setMode: (mode: ChatState['mode']) => void
  /** 设置摄入源文件路径 */
  setIngestSource: (path: string | null) => void
  /** 清空当前对话消息 */
  clearMessages: () => void
  /** 设置最大历史消息数 */
  setMaxHistoryMessages: (n: number) => void
  /** 移除最后一条助手消息（用于重新生成） */
  removeLastAssistantMessage: () => void

  // ── API 数据加载 ──

  /** 从后端加载对话列表 */
  loadConversations: () => Promise<void>
  /** 从后端加载指定对话的消息 */
  loadMessages: (conversationId: string) => Promise<void>

  // ── 辅助方法 ──

  /** 获取当前活跃对话的所有消息 */
  getActiveMessages: () => DisplayMessage[]
}

// ---------------------------------------------------------------------------
// 内部工具函数
// ---------------------------------------------------------------------------

/** 全局消息计数器，用于生成临时消息 ID（后端保存后使用后端返回的 ID） */
let messageCounter = 0

/** 生成递增消息 ID */
function nextMessageId(): string {
  messageCounter += 1
  return String(messageCounter)
}

// ---------------------------------------------------------------------------
// Store 创建
// ---------------------------------------------------------------------------

/**
 * 聊天状态管理 store
 *
 * 使用 Zustand 的 set/get 模式，所有对话和消息操作自动与后端同步。
 */
export const useChatStore = create<ChatState>((set, get) => ({
  conversations: [],
  activeConversationId: null,
  messages: [],
  isStreaming: false,
  streamingContent: '',
  mode: 'chat',
  ingestSource: null,
  maxHistoryMessages: 10,

  // ── 对话管理实现 ──

  /** 创建新对话：调用后端 API，写入 store 并激活 */
  createConversation: async () => {
    try {
      const res = await fetch('/api/wiki/chats', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: '新对话' }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      const newConv: Conversation = {
        id: data.id,
        title: data.title,
        createdAt: data.createdAt || Date.now(),
        updatedAt: data.updatedAt || Date.now(),
      }
      set((state) => ({
        conversations: [newConv, ...state.conversations],
        activeConversationId: newConv.id,
        // 切换对话时清空已加载的消息，避免串数据
        messages: [],
      }))
      return newConv.id
    } catch {
      // 后端失败时创建纯前端对话（降级处理）
      const id = `local_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
      const now = Date.now()
      const newConv: Conversation = { id, title: '新对话', createdAt: now, updatedAt: now }
      set((state) => ({
        conversations: [newConv, ...state.conversations],
        activeConversationId: id,
        messages: [],
      }))
      return id
    }
  },

  /** 删除对话：调用后端 API，移除本地数据，自动切换活跃对话 */
  deleteConversation: async (id) => {
    // 先从后端删除
    try {
      await fetch(`/api/wiki/chats/${id}`, { method: 'DELETE' })
    } catch {
      // 后端删除失败仍允许前端删除
    }
    set((state) => {
      const remaining = state.conversations.filter((c) => c.id !== id)
      const newActiveId =
        state.activeConversationId === id
          ? (remaining[0]?.id ?? null)
          : state.activeConversationId
      return {
        conversations: remaining,
        messages: state.messages.filter((m) => m.conversationId !== id),
        activeConversationId: newActiveId,
      }
    })
  },

  /** 激活指定对话：同时从后端加载该对话的消息 */
  setActiveConversation: async (id) => {
    set({ activeConversationId: id })
    if (id) {
      await get().loadMessages(id)
    }
  },

  /** 重命名对话：同时更新后端 */
  renameConversation: async (id, title) => {
    set((state) => ({
      conversations: state.conversations.map((c) =>
        c.id === id ? { ...c, title, updatedAt: Date.now() } : c,
      ),
    }))
    try {
      await fetch(`/api/wiki/chats/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      })
    } catch {
      // 后端更新失败静默处理
    }
  },

  // ── 消息管理实现 ──

  /**
   * 添加消息到当前活跃对话（同时保存到后端）
   *
   * 首条用户消息同时用于自动设置对话标题（取前 50 字符）。
   */
  addMessage: async (role, content, extra) => {
    const { activeConversationId, conversations } = get()
    if (!activeConversationId) return

    const tempId = nextMessageId()
    const newMessage: DisplayMessage = {
      id: tempId,
      role,
      content,
      timestamp: Date.now(),
      conversationId: activeConversationId,
      answerSources: extra?.answerSources,
      sourceFiles: extra?.sourceFiles,
    }

    // 首条用户消息自动作为对话标题
    const convMessages = get().messages.filter(
      (m) => m.conversationId === activeConversationId && m.role === 'user',
    )
    let updatedConversations: Conversation[]
    let newTitle: string | undefined

    if (role === 'user' && convMessages.length === 0) {
      newTitle = content.slice(0, 50)
      updatedConversations = conversations.map((c) =>
        c.id === activeConversationId
          ? { ...c, title: newTitle!, updatedAt: Date.now() }
          : c,
      )
    } else {
      updatedConversations = conversations.map((c) =>
        c.id === activeConversationId
          ? { ...c, updatedAt: Date.now() }
          : c,
      )
    }

    set({
      messages: [...get().messages, newMessage],
      conversations: updatedConversations,
    })

    // 异步保存到后端
    try {
      await fetch(`/api/wiki/chats/${activeConversationId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          role,
          content,
          answerSources: extra?.answerSources,
          sourceFiles: extra?.sourceFiles,
        }),
      })

      // 更新对话标题到后端
      if (newTitle) {
        await fetch(`/api/wiki/chats/${activeConversationId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: newTitle }),
        })
      }
    } catch {
      // 后端保存失败静默处理
    }
  },

  setMessages: (messages) => set({ messages }),
  setConversations: (conversations) => set({ conversations }),

  /** 开启/关闭流式接收状态 */
  setStreaming: (isStreaming) => set({ isStreaming }),

  /** 追加单个流式 token 到 streamingContent */
  appendStreamToken: (token) =>
    set((state) => ({
      streamingContent: state.streamingContent + token,
    })),

  /**
   * 最终化流式内容（同时保存到后端）
   *
   * 将累积的 streamingContent 固化为一条完整的助手消息，
   * 清空 streamingContent 并关闭 isStreaming 状态。
   */
  finalizeStream: async (content, references, answerSources, sourceFiles) => {
    const { activeConversationId, conversations } = get()
    if (!activeConversationId) {
      set({ isStreaming: false, streamingContent: '' })
      return
    }

    const tempId = nextMessageId()
    const newMessage: DisplayMessage = {
      id: tempId,
      role: 'assistant' as const,
      content,
      timestamp: Date.now(),
      conversationId: activeConversationId,
      references,
      answerSources,
      sourceFiles,
    }

    set({
      isStreaming: false,
      streamingContent: '',
      messages: [...get().messages, newMessage],
      conversations: conversations.map((c) =>
        c.id === activeConversationId
          ? { ...c, updatedAt: Date.now() }
          : c,
      ),
    })

    // 异步保存助手消息到后端
    try {
      await fetch(`/api/wiki/chats/${activeConversationId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          role: 'assistant',
          content,
          answerSources,
          sourceFiles,
        }),
      })
    } catch {
      // 后端保存失败静默处理
    }
  },

  setMode: (mode) => set({ mode }),
  setIngestSource: (ingestSource) => set({ ingestSource }),

  /** 清空当前活跃对话的所有消息 */
  clearMessages: () =>
    set((state) => ({
      messages: state.messages.filter(
        (m) => m.conversationId !== state.activeConversationId,
      ),
    })),

  setMaxHistoryMessages: (maxHistoryMessages) => set({ maxHistoryMessages }),

  /** 移除最后一条助手消息（用于"重新生成"场景） */
  removeLastAssistantMessage: () =>
    set((state) => {
      const activeId = state.activeConversationId
      if (!activeId) return state
      const activeMessages = state.messages.filter(
        (m) => m.conversationId === activeId,
      )
      const lastAssistantIdx = [...activeMessages]
        .reverse()
        .findIndex((m) => m.role === 'assistant')
      if (lastAssistantIdx === -1) return state
      const msgToRemove =
        activeMessages[activeMessages.length - 1 - lastAssistantIdx]
      return {
        messages: state.messages.filter((m) => m.id !== msgToRemove.id),
      }
    }),

  // ── API 数据加载 ──

  /** 从后端加载对话列表 */
  loadConversations: async () => {
    try {
      const res = await fetch('/api/wiki/chats')
      if (res.ok) {
        const data = await res.json()
        set({ conversations: data.conversations || [] })
      }
    } catch {
      // 静默失败
    }
  },

  /** 从后端加载指定对话的消息 */
  loadMessages: async (conversationId: string) => {
    try {
      const res = await fetch(`/api/wiki/chats/${conversationId}`)
      if (res.ok) {
        const data = await res.json()
        // 后端返回的消息转换为前端格式
        const msgs: DisplayMessage[] = (data.messages || []).map((msg: Record<string, unknown>) => {
          // 从 references_json 中提取 answerSources 和 sourceFiles
          const refs = msg.references as Record<string, unknown> | undefined
          return {
            id: String(msg.id),
            role: msg.role as 'user' | 'assistant' | 'system',
            content: String(msg.content || ''),
            timestamp: (msg.timestamp as number) || Date.now(),
            conversationId: String(msg.conversationId || conversationId),
            answerSources: refs?.answerSources as string[] | undefined,
            sourceFiles: refs?.sourceFiles as string[] | undefined,
            references: refs?.references as MessageReference[] | undefined,
          }
        })
        // 加载该对话的消息时，替换整个 messages（只保留当前对话的消息）
        set({
          messages: msgs,
        })
      }
    } catch {
      // 静默失败
    }
  },

  // ── 辅助方法 ──

  /** 获取当前活跃对话的消息列表 */
  getActiveMessages: () => {
    const { messages, activeConversationId } = get()
    if (!activeConversationId) return []
    return messages.filter((m) => m.conversationId === activeConversationId)
  },
}))

/**
 * 将展示用消息转换为 LLM 调用格式
 *
 * @param messages - 展示用消息列表
 * @returns LLM 调用所需的精简消息数组
 */
export function chatMessagesToLLM(
  messages: DisplayMessage[],
): { role: string; content: string }[] {
  return messages.map((m) => ({
    role: m.role,
    content: m.content,
  }))
}
