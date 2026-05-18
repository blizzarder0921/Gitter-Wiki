/**
 * README 图片路径转换工具
 *
 * GitHub 仓库 README 中的图片引用通常使用相对路径，
 * 如 ![架构图](./docs/architecture.png)，在本地渲染时浏览器无法解析。
 * 此模块提供将相对路径转换为 GitHub raw URL 的工具函数。
 */

/**
 * 从 GitHub URL 中提取 owner 和 repo
 *
 * @param githubUrl - GitHub 仓库 URL
 * @returns [owner, repo] 元组，解析失败返回 null
 */
export function extractOwnerRepo(githubUrl: string | null | undefined): [string, string] | null {
  if (!githubUrl) return null
  const m = githubUrl.match(/(?:https?:\/\/)?github\.com\/([^/]+)\/([^/.]+?)(?:\.git)?\/?$/)
  if (m) return [m[1], m[2]]
  return null
}

/**
 * 将 README 中的相对路径图片引用转换为 GitHub raw URL
 *
 * 处理 Markdown 图片语法 ![alt](path) 和 HTML <img> 标签。
 * 已是绝对 URL 的路径不做转换。
 *
 * @param content - README Markdown 文本
 * @param githubUrl - GitHub 仓库 URL，用于提取 owner/repo
 * @returns 图片路径已转换的文本
 */
export function rewriteReadmeImagePaths(
  content: string,
  githubUrl: string | null | undefined,
): string {
  const ownerRepo = extractOwnerRepo(githubUrl)
  if (!ownerRepo) return content

  const [owner, repo] = ownerRepo
  const base = `https://ghfast.top/https://raw.githubusercontent.com/${owner}/${repo}/HEAD`

  const isAbsolute = (p: string) =>
    p.startsWith('http://') || p.startsWith('https://') || p.startsWith('data:') || p.startsWith('mailto:')

  const cleanPath = (p: string) => {
    let s = p.replace(/^\.\//, '')
    if (s.startsWith('/')) s = s.slice(1)
    return s
  }

  // Markdown 图片 ![alt](path)
  let result = content.replace(
    /!\[([^\]]*)\]\(([^)]+)\)/g,
    (_match, alt: string, path: string) => {
      if (isAbsolute(path)) return _match
      return `![${alt}](${base}/${cleanPath(path)})`
    },
  )

  // HTML <img src="path">
  result = result.replace(
    /(<img\s[^>]*src=["'])([^"']+)(["'])/gi,
    (_match, prefix: string, path: string, suffix: string) => {
      if (isAbsolute(path)) return _match
      return `${prefix}${base}/${cleanPath(path)}${suffix}`
    },
  )

  return result
}
