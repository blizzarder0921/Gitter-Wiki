'use client';

/**
 * 页面底部 Footer 组件
 * 显示项目名称和简介
 */
export function Footer() {
  return (
    <div className="mt-auto pt-12 pb-4 text-center">
      <a
        href="https://github.com/blizzarder0921/Gitter-Wiki"
        target="_blank"
        rel="noopener noreferrer"
        className="text-xs text-muted-foreground/40 hover:text-muted-foreground/70 transition-colors"
      >
        Gitter - GitHub 项目本地管理工具
      </a>
    </div>
  );
}
