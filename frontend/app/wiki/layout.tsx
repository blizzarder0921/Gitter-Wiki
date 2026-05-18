'use client';

/**
 * Wiki 模块布局 -- app/wiki/layout.tsx
 *
 * Wiki 子路由的根布局，引用 Gitter 的 ThemeProvider 和字体配置。
 * 确保 Wiki 页面继承全局主题、多语言和 Toast 通知系统。
 * 布局为全高无内边距设计，由内部三栏容器自行管理尺寸。
 */
import React from 'react';

// ---------------------------------------------------------------------------
// 布局组件
// ---------------------------------------------------------------------------

/**
 * Wiki 布局包装器
 *
 * Wiki 模块使用"无 chrome"设计 -- 不包含顶部导航栏，
 * 所有 UI 控件由三栏布局内部提供。
 * 子组件通过 children 渲染实际页面内容。
 */
export default function WikiLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="h-[100dvh] w-full overflow-hidden">
      {children}
    </div>
  );
}
