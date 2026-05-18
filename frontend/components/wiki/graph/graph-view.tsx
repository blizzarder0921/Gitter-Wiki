'use client';

/**
 * 知识图谱可视化组件（vis-network 版）
 *
 * 使用 vis-network 渲染交互式知识图谱，样式与 graphify 生成的 graph.html 一致。
 * 布局：左侧图谱 + 右侧侧边栏（搜索 / 节点信息 / 项目图例）。
 * 支持项目来源着色、项目图例复选框筛选。
 *
 * 数据来源：GET /api/wiki/graph
 */

import { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { Network } from 'vis-network/standalone';
import { DataSet } from 'vis-data/standalone';
import { motion, AnimatePresence } from 'motion/react';
import {
  Loader2,
  AlertTriangle,
  Lightbulb,
  Zap,
  Target,
  FileText,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import type {
  GraphData,
  GraphNode,
  GraphInsight,
  GraphInsightType,
} from '@/lib/wiki/types';

// ---------------------------------------------------------------------------
// 常量定义
// ---------------------------------------------------------------------------

/** 项目着色方案：与 graph.html 的 Tableau10 色板风格一致 */
const PROJECT_COLORS: string[] = [
  '#4E79A7',
  '#F28E2B',
  '#E15759',
  '#76B7B2',
  '#59A14F',
  '#EDC948',
  '#B07AA1',
  '#FF9DA7',
  '#9C755F',
  '#BAB0AC',
];

/** 跨项目节点的颜色 */
const CROSS_PROJECT_COLOR = '#6366f1';

/** 无项目归属节点的颜色 */
const NO_PROJECT_COLOR = '#555555';

/** 根据项目索引获取颜色 */
function getProjectColor(projectIndex: number): string {
  return PROJECT_COLORS[projectIndex % PROJECT_COLORS.length] || NO_PROJECT_COLOR;
}

/** 根据节点连接数计算节点大小 */
function getNodeSize(linkCount: number): number {
  return Math.max(8, Math.min(40, 8 + linkCount * 3));
}

// ---------------------------------------------------------------------------
// 洞察类型图标映射
// ---------------------------------------------------------------------------

const INSIGHT_CONFIG: Record<GraphInsightType, {
  icon: typeof Lightbulb;
  label: string;
  color: string;
}> = {
  'surprising-connection': {
    icon: Zap,
    label: '意外关联',
    color: 'text-purple-500 bg-purple-50 dark:bg-purple-900/20',
  },
  'knowledge-gap': {
    icon: AlertTriangle,
    label: '知识缺口',
    color: 'text-amber-500 bg-amber-50 dark:bg-amber-900/20',
  },
  'hub-node': {
    icon: Target,
    label: '枢纽节点',
    color: 'text-blue-500 bg-blue-50 dark:bg-blue-900/20',
  },
};

// ---------------------------------------------------------------------------
// 项目图例项类型
// ---------------------------------------------------------------------------

interface ProjectLegendItem {
  source: string;
  name: string;
  color: string;
  nodeCount: number;
  visible: boolean;
}

// ---------------------------------------------------------------------------
// Props 类型
// ---------------------------------------------------------------------------

interface GraphViewProps {
  onSelectFile?: (path: string) => void;
  className?: string;
}

// ---------------------------------------------------------------------------
// 主组件
// ---------------------------------------------------------------------------

/**
 * 知识图谱可视化主组件
 *
 * 使用 vis-network 渲染，布局与 graphify 的 graph.html 一致：
 * 左侧为图谱区域，右侧为侧边栏（搜索、节点信息、项目图例）。
 */
export function GraphView({ onSelectFile, className }: GraphViewProps) {
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [insights, setInsights] = useState<GraphInsight[]>([]);
  const [insightsExpanded, setInsightsExpanded] = useState(true);

  /** 被隐藏的源文件集合 */
  const [hiddenSources, setHiddenSources] = useState<Set<string>>(new Set());

  /** vis-network 实例引用 */
  const networkRef = useRef<Network | null>(null);
  /** 图谱容器 DOM 引用 */
  const containerRef = useRef<HTMLDivElement | null>(null);
  /** vis DataSet 引用（用于动态更新节点可见性） */
  const nodesDataSetRef = useRef<any>(null);

  /** 搜索关键字 */
  const [searchQuery, setSearchQuery] = useState('');
  /** 搜索结果 */
  const [searchResults, setSearchResults] = useState<GraphNode[]>([]);
  /** 邻居节点列表 */
  const [neighbors, setNeighbors] = useState<{ id: string; label: string; color: string }[]>([]);

  /**
   * 获取知识图谱数据
   */
  const fetchGraphData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/wiki/graph');
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error || `请求失败 (${res.status})`);
      }
      const data: GraphData & { insights?: GraphInsight[] } = await res.json();
      setGraphData(data);
      setInsights(data.insights || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '获取图谱数据失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchGraphData();
  }, [fetchGraphData]);

  /** 项目图例数据 */
  const projectLegend = useMemo(() => {
    if (!graphData) return [];
    const sourceToName = graphData.sourceToName || {};
    const sourceNodeCounts = new Map<string, number>();

    for (const node of graphData.nodes) {
      for (const src of node.projectSources || []) {
        sourceNodeCounts.set(src, (sourceNodeCounts.get(src) || 0) + 1);
      }
    }

    const items: ProjectLegendItem[] = [];
    let idx = 0;
    for (const [source, count] of sourceNodeCounts) {
      items.push({
        source,
        name: sourceToName[source] || source.replace('.md', ''),
        color: getProjectColor(idx),
        nodeCount: count,
        visible: !hiddenSources.has(source),
      });
      idx++;
    }
    return items;
  }, [graphData, hiddenSources]);

  /** 构建源文件→颜色索引映射 */
  const sourceColorMap = useMemo(() => {
    const map = new Map<string, { color: string; index: number }>();
    let idx = 0;
    for (const p of projectLegend) {
      map.set(p.source, { color: p.color, index: idx });
      idx++;
    }
    return map;
  }, [projectLegend]);

  /** 计算节点颜色 */
  const getNodeColor = useCallback(
    (node: GraphNode): string => {
      const sources = node.projectSources || [];
      if (sources.length === 0) return NO_PROJECT_COLOR;
      if (sources.length === 1) {
        return sourceColorMap.get(sources[0])?.color || NO_PROJECT_COLOR;
      }
      return CROSS_PROJECT_COLOR;
    },
    [sourceColorMap],
  );

  /** 获取节点所属项目信息（用于侧边栏） */
  const getNodeProjectInfo = useCallback(
    (node: GraphNode): { source: string; name: string; color: string }[] => {
      const sourceToName = graphData?.sourceToName || {};
      const sources = node.projectSources || [];
      return sources.map((src) => ({
        source: src,
        name: sourceToName[src] || src.replace('.md', ''),
        color: sourceColorMap.get(src)?.color || NO_PROJECT_COLOR,
      }));
    },
    [graphData, sourceColorMap],
  );

  /** 切换项目图例的可见性 */
  const toggleProjectVisibility = useCallback((source: string) => {
    setHiddenSources((prev) => {
      const next = new Set(prev);
      if (next.has(source)) {
        next.delete(source);
      } else {
        next.add(source);
      }
      return next;
    });
  }, []);

  /** 全选/全不选 */
  const toggleAllProjects = useCallback(
    (hide: boolean) => {
      if (hide) {
        setHiddenSources(new Set(projectLegend.map((p) => p.source)));
      } else {
        setHiddenSources(new Set());
      }
    },
    [projectLegend],
  );

  /** 搜索处理 */
  const handleSearch = useCallback(
    (query: string) => {
      setSearchQuery(query);
      if (!query.trim() || !graphData) {
        setSearchResults([]);
        return;
      }
      const q = query.toLowerCase().trim();
      const matches = graphData.nodes
        .filter((n) => n.label.toLowerCase().includes(q))
        .slice(0, 20);
      setSearchResults(matches);
    },
    [graphData],
  );

  /** 聚焦到指定节点 */
  const focusNode = useCallback(
    (nodeId: string) => {
      const network = networkRef.current;
      if (!network) return;
      network.focus(nodeId, { scale: 1.4, animation: true });
      network.selectNodes([nodeId]);
      const node = graphData?.nodes.find((n) => n.id === nodeId);
      if (node) {
        setSelectedNode(node);
        if (onSelectFile && node.path) onSelectFile(node.path);
      }
      setSearchResults([]);
      setSearchQuery('');
    },
    [graphData, onSelectFile],
  );

  // -------------------------------------------------------------------------
  // 初始化 vis-network
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (!graphData || !containerRef.current) return;

    /** 构建 vis-network 节点数据 */
    const visNodes = graphData.nodes.map((node) => {
      const color = getNodeColor(node);
      return {
        id: node.id,
        label: node.label,
        color: {
          background: color,
          border: color,
          highlight: { background: '#e0e7ff', border: color },
          hover: { background: color, border: '#e0e7ff' },
        },
        size: getNodeSize(node.linkCount),
        font: { size: 12, color: '#333333' },
        title: node.label,
        _nodeData: node,
        _projectSources: node.projectSources || [],
      };
    });

    /** 构建 vis-network 边数据（虚线、低透明度，与 graph.html 一致） */
    const visEdges = graphData.edges
      .filter((e) => graphData.nodes.some((n) => n.id === e.source) && graphData.nodes.some((n) => n.id === e.target))
      .map((e, i) => ({
        id: i,
        from: e.source,
        to: e.target,
        dashes: true,
        width: 1,
        color: { color: '#94a3b8', opacity: 0.35 },
        arrows: { to: { enabled: true, scaleFactor: 0.5 } },
      }));

    const nodesDS = new DataSet(visNodes);
    const edgesDS = new DataSet(visEdges);
    nodesDataSetRef.current = nodesDS;

    const network = new Network(
      containerRef.current,
      { nodes: nodesDS, edges: edgesDS },
      {
        physics: {
          enabled: true,
          solver: 'forceAtlas2Based',
          forceAtlas2Based: {
            gravitationalConstant: -60,
            centralGravity: 0.005,
            springLength: 120,
            springConstant: 0.08,
            damping: 0.4,
            avoidOverlap: 0.8,
          },
          stabilization: { iterations: 200, fit: true },
        },
        interaction: {
          hover: true,
          tooltipDelay: 100,
          hideEdgesOnDrag: true,
          navigationButtons: false,
          keyboard: false,
        },
        nodes: { shape: 'dot', borderWidth: 1.5 },
        edges: { smooth: { type: 'continuous', roundness: 0.2 }, selectionWidth: 3 },
      },
    );
    networkRef.current = network;

    /** 物理模拟完成后关闭，防止持续消耗性能 */
    network.once('stabilizationIterationsDone', () => {
      network.setOptions({ physics: { enabled: false } });
    });

    /** 点击节点 → 显示节点信息 */
    network.on('click', (params: any) => {
      if (params.nodes.length > 0) {
        const nodeId = params.nodes[0];
        const node = graphData.nodes.find((n) => n.id === nodeId);
        if (node) {
          setSelectedNode(node);
          if (onSelectFile && node.path) onSelectFile(node.path);

          const neighborIds = network.getConnectedNodes(nodeId) as string[];
          const neighborItems = neighborIds.map((nid: string) => {
            const nb = graphData.nodes.find((n) => n.id === nid);
            const nbColor = nb ? getNodeColor(nb) : '#555';
            return { id: nid, label: nb?.label || nid, color: nbColor };
          });
          setNeighbors(neighborItems);
        }
      } else {
        setSelectedNode(null);
        setNeighbors([]);
      }
    });

    return () => {
      network.destroy();
      networkRef.current = null;
      nodesDataSetRef.current = null;
    };
  }, [graphData, getNodeColor, onSelectFile]);

  // -------------------------------------------------------------------------
  // 响应图例筛选：隐藏/显示节点
  // -------------------------------------------------------------------------
  useEffect(() => {
    const nodesDS = nodesDataSetRef.current;
    if (!nodesDS || !graphData) return;

    const updates = graphData.nodes.map((node) => {
      const sources = node.projectSources || [];
      let shouldHide = false;

      if (sources.length === 0) {
        shouldHide = false;
      } else if (sources.length === 1) {
        shouldHide = hiddenSources.has(sources[0]);
      } else {
        shouldHide = sources.every((s) => hiddenSources.has(s));
      }

      return { id: node.id, hidden: shouldHide };
    });

    nodesDS.update(updates);
  }, [hiddenSources, graphData]);

  // -----------------------------------------------------------------------
  // 渲染：Loading 状态
  // -----------------------------------------------------------------------
  if (loading) {
    return (
      <div className={cn('flex flex-col items-center justify-center h-full min-h-[400px] gap-4', className)}>
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ repeat: Infinity, duration: 1.5, ease: 'linear' }}
        >
          <Loader2 className="w-10 h-10 text-indigo-400" />
        </motion.div>
        <p className="text-sm text-muted-foreground">正在加载知识图谱...</p>
      </div>
    );
  }

  // -----------------------------------------------------------------------
  // 渲染：错误状态
  // -----------------------------------------------------------------------
  if (error) {
    return (
      <div className={cn('flex flex-col items-center justify-center h-full min-h-[400px] gap-3', className)}>
        <AlertTriangle className="w-10 h-10 text-red-400" />
        <p className="text-sm text-red-500">{error}</p>
        <button
          onClick={fetchGraphData}
          className="px-4 py-1.5 text-xs rounded-lg bg-indigo-500 text-white hover:bg-indigo-600 transition-colors"
        >
          重试
        </button>
      </div>
    );
  }

  // -----------------------------------------------------------------------
  // 渲染：空数据状态
  // -----------------------------------------------------------------------
  if (!graphData || graphData.nodes.length === 0) {
    return (
      <div className={cn('flex flex-col items-center justify-center h-full min-h-[400px] gap-3', className)}>
        <Network className="w-10 h-10 text-gray-300 dark:text-gray-600" />
        <p className="text-sm text-muted-foreground">暂无知识图谱数据</p>
        <p className="text-xs text-gray-400">请先运行"摄入"以构建知识图谱</p>
      </div>
    );
  }

  // -----------------------------------------------------------------------
  // 渲染：图谱主界面（与 graph.html 一致的布局）
  // -----------------------------------------------------------------------
  const allVisible = hiddenSources.size === 0;
  const allHidden = hiddenSources.size === projectLegend.length;

  return (
    <div className={cn('flex flex-col h-full min-h-[400px] gap-3', className)}>
      {/* 图谱 + 侧边栏布局 */}
      <div className="flex flex-1 rounded-xl overflow-hidden border border-gray-200 dark:border-gray-700"
        style={{ background: '#f8f9fa' }}>

        {/* 左侧：图谱区域 */}
        <div ref={containerRef} className="flex-1" style={{ minHeight: 400 }} />

        {/* 右侧：侧边栏 */}
        <div className="w-[280px] flex flex-col overflow-hidden shrink-0"
          style={{ background: '#ffffff', borderLeft: '1px solid #e5e7eb' }}>

          {/* 搜索栏 */}
          <div className="p-3" style={{ borderBottom: '1px solid #e5e7eb' }}>
            <input
              type="text"
              placeholder="搜索节点..."
              autoComplete="off"
              value={searchQuery}
              onChange={(e) => handleSearch(e.target.value)}
              className="w-full px-2.5 py-1.5 rounded-md text-sm outline-none"
              style={{
                background: '#f8f9fa',
                border: '1px solid #d1d5db',
                color: '#333333',
              }}
              onFocus={(e) => { e.target.style.borderColor = '#4E79A7'; }}
              onBlur={(e) => { e.target.style.borderColor = '#d1d5db'; }}
            />
            {/* 搜索结果 */}
            {searchResults.length > 0 && (
              <div className="mt-1 max-h-[140px] overflow-y-auto" style={{ borderBottom: '1px solid #e5e7eb' }}>
                {searchResults.map((n) => {
                  const color = getNodeColor(n);
                  return (
                    <div
                      key={n.id}
                      onClick={() => focusNode(n.id)}
                      className="px-2 py-1 cursor-pointer rounded text-xs truncate"
                      style={{ color: '#333333', borderLeft: `3px solid ${color}`, paddingLeft: 8 }}
                      onMouseEnter={(e) => { e.currentTarget.style.background = '#f0f0f0'; }}
                      onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
                    >
                      {n.label}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* 节点信息面板 */}
          <div className="p-3.5 min-h-[140px]" style={{ borderBottom: '1px solid #e5e7eb' }}>
            <h3 className="text-[13px] text-[#888] mb-2 uppercase tracking-wide">节点信息</h3>
            {selectedNode ? (
              <div className="text-[13px] leading-relaxed" style={{ color: '#555' }}>
                <div className="mb-1 font-medium" style={{ color: '#1f2937' }}>{selectedNode.label}</div>
                <div className="mb-1">类型: {selectedNode.type || 'unknown'}</div>
                <div className="mb-1">
                  项目: {getNodeProjectInfo(selectedNode).map((p) => (
                    <span
                      key={p.source}
                      className="inline-block px-1.5 py-0.5 rounded text-[11px] mr-1"
                      style={{ backgroundColor: p.color + '30', color: p.color, border: `1px solid ${p.color}50` }}
                    >
                      {p.name}
                    </span>
                  ))}
                  {(!selectedNode.projectSources || selectedNode.projectSources.length === 0) && (
                    <span style={{ color: '#999' }}>无归属</span>
                  )}
                </div>
                <div className="mb-1">连接数: {selectedNode.linkCount}</div>
                {neighbors.length > 0 && (
                  <>
                    <div className="mt-2 text-[11px]" style={{ color: '#888' }}>
                      邻居节点 ({neighbors.length})
                    </div>
                    <div className="max-h-[160px] overflow-y-auto mt-1">
                      {neighbors.map((nb) => (
                        <div
                          key={nb.id}
                          onClick={() => focusNode(nb.id)}
                          className="block px-2 py-0.5 my-0.5 rounded cursor-pointer text-xs truncate"
                          style={{ borderLeft: `3px solid ${nb.color}`, color: '#555' }}
                          onMouseEnter={(e) => { e.currentTarget.style.background = '#f0f0f0'; }}
                          onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
                        >
                          {nb.label}
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            ) : (
              <span className="italic text-sm" style={{ color: '#999' }}>点击节点查看详情</span>
            )}
          </div>

          {/* 项目图例 */}
          <div className="flex-1 overflow-y-auto p-3">
            <h3 className="text-[13px] text-[#888] mb-2 uppercase tracking-wide">项目图例</h3>
            {/* 全选/全不选 */}
            <div className="flex items-center gap-2 mb-2">
              <label className="flex items-center gap-1.5 cursor-pointer text-xs" style={{ color: '#888' }}>
                <input
                  type="checkbox"
                  checked={allVisible}
                  ref={(el) => {
                    if (el) el.indeterminate = !allVisible && !allHidden;
                  }}
                  onChange={() => toggleAllProjects(!allVisible)}
                  className="w-3.5 h-3.5 rounded cursor-pointer"
                  style={{ accentColor: '#4E79A7' }}
                />
                全选
              </label>
            </div>
            {projectLegend.map((p) => (
              <div
                key={p.source}
                onClick={() => toggleProjectVisibility(p.source)}
                className="flex items-center gap-2 py-1 px-0.5 cursor-pointer rounded text-xs transition-all"
                style={{
                  color: p.visible ? '#333333' : '#999',
                  opacity: p.visible ? 1 : 0.35,
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = '#f0f0f0'; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
              >
                <input
                  type="checkbox"
                  checked={p.visible}
                  onChange={() => toggleProjectVisibility(p.source)}
                  onClick={(e) => e.stopPropagation()}
                  className="w-3.5 h-3.5 rounded cursor-pointer shrink-0"
                  style={{ accentColor: p.color }}
                />
                <span
                  className="w-3 h-3 rounded-full shrink-0"
                  style={{ backgroundColor: p.color }}
                />
                <span className="flex-1 truncate">{p.name}</span>
                <span className="text-[11px] shrink-0" style={{ color: '#999' }}>{p.nodeCount}</span>
              </div>
            ))}
          </div>

          {/* 统计信息 */}
          <div className="px-3.5 py-2.5 text-[11px]" style={{ color: '#999', borderTop: '1px solid #e5e7eb' }}>
            {graphData.nodes.length} 节点 &middot; {graphData.edges.length} 边 &middot; {projectLegend.length} 项目
          </div>
        </div>
      </div>

      {/* 图谱洞察面板 */}
      {insights.length > 0 && (
        <div className="p-3 rounded-xl bg-amber-50/60 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-800">
          <button
            onClick={() => setInsightsExpanded(!insightsExpanded)}
            className="flex items-center gap-2 w-full text-left"
          >
            <Lightbulb className="w-4 h-4 text-amber-500" />
            <span className="text-sm font-medium text-amber-700 dark:text-amber-400">
              图谱洞察 ({insights.length})
            </span>
          </button>
          <AnimatePresence>
            {insightsExpanded && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden"
              >
                <div className="mt-2 space-y-2">
                  {insights.map((insight, idx) => {
                    const config = INSIGHT_CONFIG[insight.type];
                    const IconComp = config.icon;
                    return (
                      <div
                        key={idx}
                        className={cn(
                          'flex items-start gap-2 p-2 rounded-lg text-xs',
                          config.color,
                        )}
                      >
                        <IconComp className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                        <div className="min-w-0">
                          <span className="font-medium">{config.label}：</span>
                          <span className="text-gray-600 dark:text-gray-400">
                            {insight.description}
                          </span>
                          {insight.relatedPages.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-1">
                              {insight.relatedPages.map((page) => (
                                <button
                                  key={page}
                                  onClick={() => onSelectFile?.(page)}
                                  className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-white/60 dark:bg-gray-800/60 hover:bg-white dark:hover:bg-gray-700 transition-colors"
                                >
                                  <FileText className="w-3 h-3" />
                                  <span className="truncate max-w-[120px]">{page}</span>
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}
