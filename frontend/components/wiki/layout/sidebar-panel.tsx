'use client';

/**
 * 侧边面板 -- sidebar-panel.tsx
 *
 * 左侧可切换面板，支持"文件树"和"知识树"两种视图模式。
 * - 文件树模式：按 6 层金字塔目录分组展示 Wiki 目录结构，支持展开/收起
 * - 知识树模式：占位视图，后续集成知识图谱树形导航
 *
 * 金字塔目录结构：
 *   _home.md  → 首页入口
 *   basics/   → 基础信息
 *   guides/   → 使用指南
 *   internals/→ 深度解析
 *   decisions/→ 技术决策
 *
 * 使用 ScrollArea 处理长列表滚动，遵循 Gitter 设计风格。
 */
import React, { useState, useCallback, useMemo } from 'react';
import { toast } from 'sonner';
import {
  Folder,
  FolderOpen,
  FileText,
  ChevronRight,
  Network,
  File,
  Home,
  Loader2,
  RefreshCw,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Button } from '@/components/ui/button';
import type { FileNode, WikiView } from '@/lib/wiki/types';

// ---------------------------------------------------------------------------
// 常量定义
// ---------------------------------------------------------------------------

/** 目录名到中文标签的映射 */
const DIRECTORY_LABELS: Record<string, string> = {
  basics: '基础信息',
  guides: '使用指南',
  internals: '深度解析',
  decisions: '技术决策',
};

/** 目录的固定显示顺序（按金字塔层级从底到顶） */
const DIRECTORY_ORDER = ['basics', 'guides', 'internals', 'decisions'];

// ---------------------------------------------------------------------------
// Props 类型定义
// ---------------------------------------------------------------------------

/** 侧边面板组件属性 */
interface SidebarPanelProps {
  /** 文件树数据 */
  fileTree: FileNode[];
  /** 当前选中的文件路径 */
  selectedFile: string | null;
  /** 文件选择回调 */
  onSelectFile: (path: string) => void;
  /** 当前视图类型（用于联动） */
  activeView: WikiView;
  /** 视图切换回调 */
  onViewChange: (view: WikiView) => void;
  /** 是否加载中 */
  loading?: boolean;
  /** 刷新知识库回调 */
  onRefreshKnowledge?: () => Promise<void>;
}

/** 面板视图模式 */
type PanelMode = 'files' | 'knowledge';

// ---------------------------------------------------------------------------
// 子组件：递归文件树节点
// ---------------------------------------------------------------------------

/**
 * 递归树节点行组件
 * 每行展示文件/目录图标、名称，目录可展开/收起
 */
function FileTreeRow({
  node,
  depth,
  selectedPath,
  onSelect,
}: {
  node: FileNode;
  depth: number;
  selectedPath: string | null;
  onSelect: (path: string) => void;
}) {
  // 目录展开/收起状态
  const [expanded, setExpanded] = useState(depth < 1);

  /** 切换目录展开/收起 */
  const toggleExpand = useCallback(() => {
    if (node.is_dir) setExpanded((prev) => !prev);
  }, [node.is_dir]);

  /** 点击选中文件 */
  const handleClick = useCallback(() => {
    if (!node.is_dir) onSelect(node.path);
    else toggleExpand();
  }, [node.is_dir, node.path, onSelect, toggleExpand]);

  const isSelected = selectedPath === node.path;
  const hasChildren = node.is_dir && node.children && node.children.length > 0;

  return (
    <div>
      {/* 当前行 */}
      <button
        onClick={handleClick}
        className={cn(
          'flex items-center gap-1.5 w-full px-2 py-1 rounded-md text-sm transition-colors text-left',
          isSelected
            ? 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300'
            : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700/50',
        )}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        title={node.name}
      >
        {/* 展开/收起箭头（仅目录） */}
        {node.is_dir ? (
          <>
            <ChevronRight
              className={cn(
                'w-3.5 h-3.5 flex-shrink-0 transition-transform',
                expanded && 'rotate-90',
              )}
            />
            {expanded ? (
              <FolderOpen className="w-4 h-4 flex-shrink-0 text-yellow-500" />
            ) : (
              <Folder className="w-4 h-4 flex-shrink-0 text-yellow-500" />
            )}
          </>
        ) : (
          <>
            <span className="w-3.5 h-3.5 flex-shrink-0" />
            <FileText className="w-4 h-4 flex-shrink-0 text-blue-500" />
          </>
        )}

        {/* 文件名 */}
        <span className="truncate flex-1">{node.name}</span>
      </button>

      {/* 递归渲染子节点 */}
      {node.is_dir && expanded && hasChildren && (
        <div>
          {node.children!.map((child) => (
            <FileTreeRow
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedPath={selectedPath}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 子组件：金字塔目录分组
// ---------------------------------------------------------------------------

/**
 * 金字塔目录分组组件
 *
 * 将文件树按 basics/guides/internals/decisions 目录分组显示，
 * _home.md 作为首页入口显示在最顶部。
 * 每个目录显示中文标签，可折叠展开。
 */
function PyramidFileTree({
  fileTree,
  selectedFile,
  onSelectFile,
}: {
  fileTree: FileNode[];
  selectedFile: string | null;
  onSelectFile: (path: string) => void;
}) {
  // 各目录的展开/收起状态，默认全部展开
  const [expandedDirs, setExpandedDirs] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {};
    DIRECTORY_ORDER.forEach((dir) => {
      initial[dir] = true;
    });
    return initial;
  });

  /** 切换目录展开/收起 */
  const toggleDir = useCallback((dirName: string) => {
    setExpandedDirs((prev) => ({ ...prev, [dirName]: !prev[dirName] }));
  }, []);

  // 将文件树节点分类：_home.md / 目录节点 / 其他文件
  const { homeNode, dirNodes, otherNodes } = useMemo(() => {
    const home: FileNode[] = [];
    const dirs: Record<string, FileNode> = {};
    const others: FileNode[] = [];

    for (const node of fileTree) {
      if (!node.is_dir && node.name === '_home.md') {
        home.push(node);
      } else if (node.is_dir && DIRECTORY_ORDER.includes(node.name)) {
        dirs[node.name] = node;
      } else if (node.is_dir) {
        // 非标准目录也保留，放在最后
        others.push(node);
      } else {
        // 根目录下的其他文件
        others.push(node);
      }
    }

    return { homeNode: home, dirNodes: dirs, otherNodes: others };
  }, [fileTree]);

  return (
    <div className="py-1">
      {/* 首页入口：_home.md */}
      {homeNode.map((node) => (
        <button
          key={node.path}
          onClick={() => onSelectFile(node.path)}
          className={cn(
            'flex items-center gap-1.5 w-full px-2 py-1.5 rounded-md text-sm transition-colors text-left mb-1',
            selectedFile === node.path
              ? 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300'
              : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700/50',
          )}
          style={{ paddingLeft: '8px' }}
          title="_home.md"
        >
          <Home className="w-4 h-4 flex-shrink-0 text-purple-500" />
          <span className="truncate flex-1 font-medium">首页</span>
        </button>
      ))}

      {/* 分隔线 */}
      {homeNode.length > 0 && (dirNodes || otherNodes) && (
        <div className="mx-2 my-1.5 border-t border-gray-200/60 dark:border-gray-700/40" />
      )}

      {/* 按固定顺序渲染金字塔目录 */}
      {DIRECTORY_ORDER.map((dirName) => {
        const dirNode = dirNodes[dirName];
        if (!dirNode) return null;

        const isExpanded = expandedDirs[dirName] !== false;
        const label = DIRECTORY_LABELS[dirName] || dirName;
        const hasChildren = dirNode.children && dirNode.children.length > 0;

        return (
          <div key={dirName} className="mb-0.5">
            {/* 目录标题行 */}
            <button
              onClick={() => toggleDir(dirName)}
              className="flex items-center gap-1.5 w-full px-2 py-1 rounded-md text-sm transition-colors text-left hover:bg-gray-100 dark:hover:bg-gray-700/50"
              style={{ paddingLeft: '8px' }}
              title={label}
            >
              <ChevronRight
                className={cn(
                  'w-3.5 h-3.5 flex-shrink-0 transition-transform',
                  isExpanded && 'rotate-90',
                )}
              />
              {isExpanded ? (
                <FolderOpen className="w-4 h-4 flex-shrink-0 text-yellow-500" />
              ) : (
                <Folder className="w-4 h-4 flex-shrink-0 text-yellow-500" />
              )}
              <span className="truncate flex-1 font-medium text-gray-700 dark:text-gray-300">
                {label}
              </span>
              {/* 文件数量角标 */}
              {hasChildren && (
                <span className="text-xs text-gray-400 dark:text-gray-500 tabular-nums">
                  {dirNode.children!.length}
                </span>
              )}
            </button>

            {/* 目录内文件列表 */}
            {isExpanded && hasChildren && (
              <div>
                {dirNode.children!.map((child) => (
                  <FileTreeRow
                    key={child.path}
                    node={child}
                    depth={1}
                    selectedPath={selectedFile}
                    onSelect={onSelectFile}
                  />
                ))}
              </div>
            )}
          </div>
        );
      })}

      {/* 非标准目录和其他根文件 */}
      {otherNodes.map((node) => (
        <FileTreeRow
          key={node.path}
          node={node}
          depth={0}
          selectedPath={selectedFile}
          onSelect={onSelectFile}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 主组件
// ---------------------------------------------------------------------------

/**
 * 侧边面板组件
 *
 * 顶部展示文件树/知识树切换标签，下方为可滚动内容区。
 * 文件树模式下按金字塔目录分组渲染 FileNode 结构。
 * 底部提供"刷新知识库"操作按钮。
 */
export function SidebarPanel({
  fileTree,
  selectedFile,
  onSelectFile,
  activeView,
  onViewChange,
  loading = false,
  onRefreshKnowledge,
}: SidebarPanelProps) {
  const [mode, setMode] = useState<PanelMode>('files');

  // 刷新知识库的加载状态
  const [refreshing, setRefreshing] = useState(false);

  /** 触发刷新知识库 */
  const handleRefreshKnowledge = useCallback(async () => {
    if (!onRefreshKnowledge || refreshing) return;
    setRefreshing(true);
    try {
      await onRefreshKnowledge();
      toast.success('知识库刷新完成');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '刷新知识库失败';
      toast.error(msg);
    } finally {
      setRefreshing(false);
    }
  }, [onRefreshKnowledge, refreshing]);

  /** 文件树 Tab 配置 */
  const tabs: { key: PanelMode; icon: React.ComponentType<{ className?: string }>; label: string }[] = [
    { key: 'files', icon: File, label: '文件' },
    { key: 'knowledge', icon: Network, label: '知识' },
  ];

  return (
    <div className="flex flex-col h-full">
      {/* 顶部 Tab 切换 */}
      <div className="flex items-center gap-1 px-3 py-2.5 border-b border-gray-200/60 dark:border-gray-700/60">
        {tabs.map((tab) => {
          const isActive = mode === tab.key;
          const Icon = tab.icon;
          return (
            <Button
              key={tab.key}
              variant="ghost"
              size="sm"
              onClick={() => setMode(tab.key)}
              className={cn(
                'h-7 px-3 text-xs gap-1.5 rounded-lg',
                isActive
                  ? 'bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400'
                  : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300',
              )}
            >
              <Icon className="w-3.5 h-3.5" />
              {tab.label}
            </Button>
          );
        })}
      </div>

      {/* 内容区 */}
      <ScrollArea className="flex-1 min-h-0">
        {mode === 'files' ? (
          // 文件树视图
          loading ? (
            <div className="flex items-center justify-center py-12 text-sm text-gray-400">
              加载中...
            </div>
          ) : fileTree.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
              <FileText className="w-8 h-8 text-gray-300 dark:text-gray-600 mb-2" />
              <p className="text-sm text-gray-400">暂无 Wiki 文件</p>
              <p className="text-xs text-gray-400 mt-1">
                点击下方「编译知识库」按钮生成 Wiki 页面
              </p>
            </div>
          ) : (
            <PyramidFileTree
              fileTree={fileTree}
              selectedFile={selectedFile}
              onSelectFile={onSelectFile}
            />
          )
        ) : (
          // 知识树视图（占位）
          <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
            <Network className="w-8 h-8 text-gray-300 dark:text-gray-600 mb-2" />
            <p className="text-sm text-gray-400">知识树视图</p>
            <p className="text-xs text-gray-400 mt-1">即将推出</p>
          </div>
        )}
      </ScrollArea>

      {/* 底部操作按钮区 */}
      <div className="flex flex-col gap-1.5 px-3 py-2.5 border-t border-gray-200/60 dark:border-gray-700/60">
        {/* 刷新知识库按钮 */}
        {onRefreshKnowledge && (
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefreshKnowledge}
            disabled={refreshing}
            className="w-full h-8 text-xs gap-1.5 justify-center"
          >
            {refreshing ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <RefreshCw className="w-3.5 h-3.5" />
            )}
            {refreshing ? '刷新中...' : '刷新知识库'}
          </Button>
        )}
      </div>
    </div>
  );
}

export default SidebarPanel;
