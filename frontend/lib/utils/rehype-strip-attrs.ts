/**
 * rehype 插件：移除 React 不识别的 HTML 属性
 *
 * rehype-raw 将 HTML 原始属性（如 valign、bgcolor、border 等）
 * 转为驼峰形式传给 React，但 React 不识别这些属性会报控制台警告。
 * 本插件在 hast 树中提前移除这些属性，避免警告。
 */

import type { Root } from 'hast';

/** React 不识别但 HTML 中常见的属性列表 */
const REACT_IGNORED_ATTRS = new Set([
  'valign',
  'bgcolor',
  'border',
  'cellpadding',
  'cellspacing',
  'frame',
  'rules',
  'summary',
  'width',
  'height',
  'align',
  'char',
  'charoff',
  'nowrap',
  'scope',
  'abbr',
  'axis',
  'bgcolor',
  'clear',
  'hspace',
  'vspace',
  'noshade',
  'nowrap',
  'color',
  'size',
  'face',
  'background',
  'text',
  'link',
  'vlink',
  'alink',
]);

/**
 * 递归移除 hast 节点中 React 不识别的属性
 */
function cleanNode(node: any): void {
  if (node && node.properties) {
    for (const key of Object.keys(node.properties)) {
      if (REACT_IGNORED_ATTRS.has(key)) {
        delete node.properties[key];
      }
    }
  }
  if (node && node.children) {
    for (const child of node.children) {
      cleanNode(child);
    }
  }
}

/**
 * rehype 插件：清理 React 不识别的 HTML 属性
 */
export function rehypeStripReactIgnoredAttrs(): (tree: Root) => void {
  return (tree: Root) => {
    cleanNode(tree);
  };
}
