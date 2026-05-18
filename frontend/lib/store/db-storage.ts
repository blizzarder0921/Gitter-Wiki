/**
 * 混合存储适配器（localStorage + SQLite 双重持久化）
 *
 * 策略：
 *   1. 写入：localStorage（同步主存储）+ SQLite（异步备份 via fetch/sendBeacon）
 *   2. 读取：localStorage → 服务端预加载数据 → 同步 XHR（兜底）
 *   3. 页面关闭：beforeunload 时 sendBeacon 最终同步到 SQLite
 *
 * 换机/清缓存恢复链路（修复同步 XHR 不可靠问题）：
 *   SettingsPreloader 服务端组件在 HTML 渲染时将数据库设置注入为
 *   <script id="__gitter_settings_preload__"> 标签，
 *   getItem 在 localStorage 为空时优先读取此标签，100% 可靠。
 */
import type { StateStorage } from 'zustand/middleware'

const DB_SYNC_KEY = 'settings-storage'
const PRELOAD_SCRIPT_ID = '__gitter_settings_preload__'

/**
 * 判断当前是否在浏览器环境
 */
function isBrowser(): boolean {
  return typeof window !== 'undefined'
}

/**
 * 将设置数据异步同步到 SQLite 数据库
 * 优先使用 fetch，失败时回退到 sendBeacon
 */
function syncToDb(value: string): void {
  if (!isBrowser()) return

  fetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain' },
    body: value,
  }).catch(() => {
    try {
      navigator.sendBeacon(
        '/api/settings',
        new Blob([value], { type: 'text/plain' }),
      )
    } catch {
      // sendBeacon 也失败，静默忽略（localStorage 中仍有数据）
    }
  })
}

/**
 * 从服务端预加载的 script 标签读取设置数据
 *
 * SettingsPreloader 在 SSR 时将 DB 中的设置 JSON 注入为：
 *   <script id="__gitter_settings_preload__" type="application/json">...</script>
 *
 * 这是换机/清缓存场景下的主要恢复路径，
 * 相比同步 XHR 100% 可靠且不阻塞主线程。
 */
function loadFromPreload(): string | null {
  if (!isBrowser()) return null

  try {
    const el = document.getElementById(PRELOAD_SCRIPT_ID)
    if (!el || !el.textContent) return null

    const text = el.textContent.trim()
    if (!text || text === '{}') return null

    JSON.parse(text)
    return text
  } catch {
    return null
  }
}

/**
 * 从 SQLite 数据库同步读取设置（兜底恢复路径）
 *
 * 仅在 service worker / 非 SSR 等无法使用预加载标签的特殊场景下触发。
 * 同步 XHR 在现代浏览器中可能抛出 InvalidAccessError，
 * 因此仅作为最后的兜底手段。
 *
 * @deprecated 优先使用服务端预加载（loadFromPreload）
 */
function loadFromDbSync(): string | null {
  if (!isBrowser()) return null

  try {
    const xhr = new XMLHttpRequest()
    xhr.open('GET', '/api/settings', false)
    xhr.send()
    if (xhr.status === 200) {
      const text = xhr.responseText
      if (text && text !== '{}') {
        try {
          JSON.parse(text)
          return text
        } catch {
          // JSON 无效
        }
      }
    }
  } catch {
    // 同步 XHR 不可用（浏览器限制）
  }

  return null
}

// 页面关闭前最终同步到 SQLite
if (isBrowser()) {
  window.addEventListener('beforeunload', () => {
    const value = localStorage.getItem(DB_SYNC_KEY)
    if (value) {
      try {
        navigator.sendBeacon(
          '/api/settings',
          new Blob([value], { type: 'text/plain' }),
        )
      } catch {
        // 静默失败
      }
    }
  })
}

/**
 * 混合存储适配器
 *
 * 读取优先级（换机恢复链）：
 *   1. localStorage           → 浏览器本地缓存（最快）
 *   2. 服务端预加载 script 标签  → SSR 注入（可靠，无网络请求）
 *   3. 同步 XHR /api/settings  → 兜底恢复（可能因浏览器限制失败）
 */
const dbStorage: StateStorage = {
  getItem: (name: string): string | null => {
    if (!isBrowser()) return null

    // 第一优先：localStorage 缓存
    const localValue = localStorage.getItem(name)
    if (localValue) return localValue

    // 第二优先：服务端预加载数据（换机/清缓存场景的主要恢复路径）
    if (name === DB_SYNC_KEY) {
      const preloadValue = loadFromPreload()
      if (preloadValue) {
        localStorage.setItem(name, preloadValue)
        return preloadValue
      }

      // 第三优先：同步 XHR 兜底（仅限非标准 SSR 环境）
      const dbValue = loadFromDbSync()
      if (dbValue) {
        localStorage.setItem(name, dbValue)
        return dbValue
      }
    }

    return null
  },

  setItem: (name: string, value: string): void => {
    if (!isBrowser()) return
    localStorage.setItem(name, value)

    if (name === DB_SYNC_KEY) {
      syncToDb(value)
    }
  },

  removeItem: (name: string): void => {
    if (!isBrowser()) return
    localStorage.removeItem(name)

    if (name === DB_SYNC_KEY) {
      fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'text/plain' },
        body: '{}',
      }).catch(() => {})
    }
  },
}

export default dbStorage
