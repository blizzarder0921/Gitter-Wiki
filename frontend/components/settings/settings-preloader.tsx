const SETTINGS_KEY = 'settings-storage'
const PRELOAD_SCRIPT_ID = '__gitter_settings_preload__'

/**
 * 设置预加载服务端组件
 *
 * 在 SSR 阶段从后端 API 读取 SQLite 中的设置数据，
 * 注入为 <script type="application/json"> 标签。
 * 客户端 Zustand store 初始化时通过 db-storage.ts 的
 * loadFromPreload() 读取此标签，确保换机/清缓存后设置不丢失。
 *
 * 相比原客户端组件方案，服务端组件在 HTML 响应中即包含设置数据，
 * 无需等待客户端异步请求，100% 可靠。
 */
export async function SettingsPreloader() {
  let settingsJson: string | null = null

  try {
    const res = await fetch('http://localhost:8000/api/settings', {
      cache: 'no-store',
    })
    if (res.ok) {
      const data = await res.json()
      const raw = data.settings?.[SETTINGS_KEY]
      if (raw && raw !== '{}') {
        JSON.parse(raw)
        settingsJson = raw
      }
    }
  } catch {
    // 后端未启动或请求失败，不注入预加载数据，客户端使用默认值
  }

  if (!settingsJson) return null

  return (
    <script
      id={PRELOAD_SCRIPT_ID}
      type="application/json"
      data-key={SETTINGS_KEY}
      dangerouslySetInnerHTML={{ __html: settingsJson }}
    />
  )
}

export { PRELOAD_SCRIPT_ID }
