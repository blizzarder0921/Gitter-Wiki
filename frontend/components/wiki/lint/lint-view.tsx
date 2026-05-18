'use client';

/**
 * Lint 检查结果展示组件
 * 按严重程度分组显示 Wiki 页面中的问题，支持跳转到对应页面
 */
import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  AlertTriangle,
  AlertCircle,
  Info,
  Loader2,
  RefreshCw,
  ExternalLink,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';
import type { LintResult as LintResultType } from '@/lib/wiki/types';

/** Lint 严重程度映射配置 */
const SEVERITY_CONFIG: Record<string, {
  icon: typeof AlertTriangle;
  color: string;
  bgColor: string;
  label: string;
}> = {
  error: { icon: AlertTriangle, color: 'text-red-500', bgColor: 'bg-red-50 dark:bg-red-900/20', label: '错误' },
  warning: { icon: AlertCircle, color: 'text-yellow-500', bgColor: 'bg-yellow-50 dark:bg-yellow-900/20', label: '警告' },
  info: { icon: Info, color: 'text-blue-500', bgColor: 'bg-blue-50 dark:bg-blue-900/20', label: '提示' },
};

interface LintViewProps {
  onNavigate?: (pagePath: string) => void;
  className?: string;
}

/**
 * Lint 检查视图
 * 加载并展示 Wiki 页面的结构性和语义性问题
 */
export function LintView({ onNavigate }: LintViewProps) {
  const [results, setResults] = useState<LintResultType[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** 加载 Lint 检查结果 */
  const loadResults = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/wiki/lint');
      if (res.ok) {
        const data = await res.json();
        setResults(data.results || []);
      } else {
        setError('加载 Lint 结果失败');
      }
    } catch {
      setError('加载 Lint 结果失败');
    } finally {
      setLoading(false);
    }
  };

  /** 运行 Lint 检查 */
  const runLint = async () => {
    setRunning(true);
    setError(null);
    try {
      const res = await fetch('/api/wiki/lint', { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setResults(data.results || []);
      } else {
        setError('运行 Lint 检查失败');
      }
    } catch {
      setError('运行 Lint 检查失败');
    } finally {
      setRunning(false);
    }
  };

  useEffect(() => {
    loadResults();
  }, []);

  /** 按严重程度分组 */
  const grouped = results.reduce((acc, r) => {
    const sev = r.severity || 'info';
    if (!acc[sev]) acc[sev] = [];
    acc[sev].push(r);
    return acc;
  }, {} as Record<string, LintResultType[]>);

  const severityOrder = ['error', 'warning', 'info'];

  return (
    <div className="flex flex-col h-full">
      {/* 头部操作栏 */}
      <div className="flex items-center justify-between p-4 border-b">
        <div className="flex items-center gap-2">
          <RefreshCw className="w-4 h-4 text-purple-500" />
          <h3 className="font-semibold text-sm">Lint 检查</h3>
          {results.length > 0 && (
            <span className="text-xs text-gray-400">{results.length} 个问题</span>
          )}
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={runLint}
          disabled={running}
          className="h-7 text-xs"
        >
          {running ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" />
          ) : (
            <RefreshCw className="w-3.5 h-3.5 mr-1" />
          )}
          运行检查
        </Button>
      </div>

      {/* 内容区 */}
      <ScrollArea className="flex-1">
        <div className="p-4 space-y-4">
          {/* 加载状态 */}
          {loading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-6 h-6 text-gray-400 animate-spin" />
            </div>
          )}

          {/* 错误状态 */}
          {error && !loading && (
            <div className="flex flex-col items-center justify-center py-12 gap-3">
              <AlertCircle className="w-8 h-8 text-red-400" />
              <p className="text-sm text-gray-500">{error}</p>
              <Button size="sm" variant="outline" onClick={loadResults}>
                重试
              </Button>
            </div>
          )}

          {/* 空状态 */}
          {!loading && !error && results.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-gray-400">
              <RefreshCw className="w-8 h-8 mb-3 opacity-50" />
              <p className="text-sm">暂无 Lint 检查结果</p>
              <p className="text-xs mt-1">点击"运行检查"扫描 Wiki 页面问题</p>
            </div>
          )}

          {/* 结果列表 */}
          <AnimatePresence>
            {!loading &&
              severityOrder.map((severity) => {
                const items = grouped[severity];
                if (!items || items.length === 0) return null;
                const config = SEVERITY_CONFIG[severity] || SEVERITY_CONFIG.info;
                const Icon = config.icon;

                return (
                  <motion.div
                    key={severity}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="space-y-2"
                  >
                    <div className="flex items-center gap-2 px-1">
                      <Icon className={cn('w-4 h-4', config.color)} />
                      <span className={cn('text-xs font-medium', config.color)}>
                        {config.label}
                      </span>
                      <span className="text-xs text-gray-400">({items.length})</span>
                    </div>

                    {items.map((item, idx) => (
                      <div
                        key={idx}
                        className={cn(
                          'rounded-xl p-3 cursor-pointer transition-colors',
                          config.bgColor,
                          'hover:opacity-80',
                        )}
                        onClick={() => {
                          if (item.page && onNavigate) onNavigate(item.page);
                        }}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium truncate">{item.message}</p>
                            {item.page && (
                              <p className="text-xs text-gray-400 mt-1 truncate font-mono">
                                {item.page}
                              </p>
                            )}
                            {item.detail && (
                              <p className="text-xs text-gray-500 mt-1 line-clamp-2">
                                {item.detail}
                              </p>
                            )}
                          </div>
                          {item.page && (
                            <ExternalLink className="w-3.5 h-3.5 text-gray-400 shrink-0 mt-0.5" />
                          )}
                        </div>
                      </div>
                    ))}
                  </motion.div>
                );
              })}
          </AnimatePresence>
        </div>
      </ScrollArea>
    </div>
  );
}
