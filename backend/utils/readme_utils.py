import re
from typing import Optional


def rewrite_readme_image_paths(
    readme_content: str, owner: str, repo: str, branch: str = "HEAD"
) -> str:
    """将 README 中的相对路径图片引用转换为 GitHub raw URL

    GitHub 仓库的 README.md 中，图片引用通常使用相对路径，
    如 ![架构图](./docs/architecture.png)，在本地渲染时浏览器无法解析。
    此函数将这些相对路径转换为 https://raw.githubusercontent.com/... 绝对 URL。

    同时处理 HTML <img> 标签中的 src 属性。

    Args:
        readme_content: README 原始 Markdown 文本
        owner: 仓库所有者
        repo: 仓库名称
        branch: 分支名，默认 HEAD
    Returns:
        图片路径已转换的 README 文本
    """
    if not readme_content:
        return readme_content

    base_url = f"https://ghfast.top/https://raw.githubusercontent.com/{owner}/{repo}/{branch}"

    def _is_absolute_url(path: str) -> bool:
        return path.startswith(("http://", "https://", "data:", "mailto:", "ftp://"))

    def _clean_relative_path(path: str) -> str:
        path = path.lstrip("./")
        if path.startswith("/"):
            path = path[1:]
        return path

    # 处理 Markdown 图片语法 ![alt](path)
    def replace_md_image(match: re.Match) -> str:
        alt = match.group(1)
        path = match.group(2)
        if _is_absolute_url(path):
            return match.group(0)
        clean_path = _clean_relative_path(path)
        return f"![{alt}]({base_url}/{clean_path})"

    # 处理 Markdown 链接中的图片引用 [![alt](img)](link) — 内层图片
    result = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replace_md_image, readme_content)

    # 处理 HTML <img> 标签中的 src 属性
    def replace_html_img_src(match: re.Match) -> str:
        prefix = match.group(1)
        path = match.group(2)
        suffix = match.group(3)
        if _is_absolute_url(path):
            return match.group(0)
        clean_path = _clean_relative_path(path)
        return f'{prefix}{base_url}/{clean_path}{suffix}'

    result = re.sub(
        r'(<img\s[^>]*src=["\'])([^"\']+)(["\'])',
        replace_html_img_src,
        result,
        flags=re.IGNORECASE,
    )

    return result


def extract_owner_repo(github_url: str) -> Optional[tuple[str, str]]:
    """从 GitHub URL 中提取 owner 和 repo

    支持的格式：
    - https://github.com/owner/repo
    - https://github.com/owner/repo.git
    - github.com/owner/repo
    - git@github.com:owner/repo.git

    Args:
        github_url: GitHub 仓库 URL
    Returns:
        (owner, repo) 元组，解析失败返回 None
    """
    if not github_url:
        return None

    # HTTPS 格式
    m = re.match(
        r"(?:https?://)?github\.com/([^/]+)/([^/.]+?)(?:\.git)?/?$", github_url
    )
    if m:
        return m.group(1), m.group(2)

    # SSH 格式
    m = re.match(r"git@github\.com:([^/]+)/([^/.]+?)(?:\.git)?$", github_url)
    if m:
        return m.group(1), m.group(2)

    return None
