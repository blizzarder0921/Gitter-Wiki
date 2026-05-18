'use client';

/**
 * 深度研究面板
 * 展示研究任务列表、状态和进度，支持启动新的深度研究
 */
import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  FlaskConical,
  Loader2,
  Search,
  Globe,
  FileText,
  CheckCircle2,
  XCircle,
  Clock,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';
import { useResearchStore } from '@/stores/research-store';
import { useSettingsStore } from '@/lib/store/settings';
import type { ResearchTask } from '@/lib/wiki/types';

interface ResearchPanelProps {
  className?: string;
}

/** 研究任务状态配置 */
const STATUS_CONFIG: Record<string, {
  icon: typeof Clock;
  color: string;
  label: string;
}> = {
  queued: { icon: Clock, color: 'text-gray-400', label: '排队中' },
  searching: { icon: Globe, color: 'text-blue-500', label: '搜索中' },
  synthesizing: { icon: FileText, color: 'text-purple-500', label: '综合分析中' },
  saving: { icon: FileText, color: 'text-purple-500', label: '保存中' },
  done: { icon: CheckCircle2, color: 'text-green-500', label: '已完成' },
  error: { icon: XCircle, color: 'text-red-500', label: '失败' },
};

/**
 * 深度研究面板
 * 管理研究任务的生命周期
 */
export function ResearchPanel({ className }: ResearchPanelProps) {
  const [tasks, setTasks] = useState<ResearchTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [topic, setTopic] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const researchSearchProvider = useSettingsStore((s) => s.researchSearchProvider);
  const researchApiKey = useSettingsStore((s) => s.researchApiKey);

  /** 加载研究任务列表 */
  const loadTasks = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/wiki/research');
      if (res.ok) {
        const data = await res.json();
        setTasks(data.tasks || []);
        // 同步到全局 ResearchStore，供其他组件读取任务状态
        useResearchStore.getState().setTasks(data.tasks || []);
      }
    } catch {
      // 静默失败
    } finally {
      setLoading(false);
    }
  }, []);

  /* eslint-disable react-hooks/set-state-in-effect -- 组件挂载时加载数据 */
  useEffect(() => {
    loadTasks();
  }, [loadTasks]);
  /* eslint-enable react-hooks/set-state-in-effect */

  /** 定时刷新运行中的任务 */
  useEffect(() => {
    const hasRunning = tasks.some(
      (t) => t.status === 'searching' || t.status === 'synthesizing' || t.status === 'saving' || t.status === 'queued',
    );
    if (!hasRunning) return;

    const interval = setInterval(loadTasks, 3000);
    return () => clearInterval(interval);
  }, [tasks, loadTasks]);

  /** 触发新的深度研究 */
  const handleStartResearch = async () => {
    if (!topic.trim() || submitting) return;
    setSubmitting(true);
    try {
      const res = await fetch('/api/wiki/research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic: topic.trim(),
          searchProvider: researchSearchProvider,
          searchApiKey: researchApiKey,
        }),
      });
      if (res.ok) {
        setTopic('');
        await loadTasks();
      }
    } catch {
      // 静默处理
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* 头部 */}
      <div className="flex items-center justify-between p-4 border-b">
        <div className="flex items-center gap-2">
          <FlaskConical className="w-4 h-4 text-purple-500" />
          <h3 className="font-semibold text-sm">深度研究</h3>
          {tasks.length > 0 && (
            <span className="text-xs text-gray-400">{tasks.length} 个任务</span>
          )}
        </div>
      </div>

      {/* 新增研究输入区 */}
      <div className="p-3 border-b bg-gray-50/50 dark:bg-gray-800/30">
        <div className="flex gap-2">
          <Input
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="输入研究主题..."
            className="h-8 text-sm"
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleStartResearch();
            }}
          />
          <Button
            size="sm"
            onClick={handleStartResearch}
            disabled={!topic.trim() || submitting}
            className="h-8 shrink-0"
          >
            {submitting ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Search className="w-3.5 h-3.5" />
            )}
          </Button>
        </div>
      </div>

      {/* 任务列表 */}
      <ScrollArea className="flex-1">
        <div className="p-3 space-y-2">
          {/* 加载状态 */}
          {loading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-6 h-6 text-gray-400 animate-spin" />
            </div>
          )}

          {/* 空状态 */}
          {!loading && tasks.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-gray-400">
              <FlaskConical className="w-8 h-8 mb-3 opacity-50" />
              <p className="text-sm">暂无研究任务</p>
              <p className="text-xs mt-1">输入主题启动 AI 自动网络搜索和知识综合</p>
            </div>
          )}

          {/* 任务列表 */}
          <AnimatePresence>
            {tasks.map((task) => {
              const config = STATUS_CONFIG[task.status] || STATUS_CONFIG.queued;
              const StatusIcon = config.icon;
              const isRunning =
                task.status === 'searching' ||
                task.status === 'synthesizing' ||
                task.status === 'saving';

              return (
                <motion.div
                  key={task.id}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  className={cn(
                    'rounded-xl p-3 transition-colors',
                    task.status === 'done'
                      ? 'bg-green-50/50 dark:bg-green-900/10'
                      : task.status === 'error'
                        ? 'bg-red-50/50 dark:bg-red-900/10'
                        : 'bg-gray-50 dark:bg-gray-800/50',
                  )}
                >
                  {/* 状态和标题 */}
                  <div className="flex items-start gap-2">
                    {isRunning ? (
                      <Loader2 className="w-4 h-4 text-purple-500 animate-spin shrink-0 mt-0.5" />
                    ) : (
                      <StatusIcon className={cn('w-4 h-4 shrink-0 mt-0.5', config.color)} />
                    )}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{task.topic}</p>
                      <div className="flex items-center gap-2 mt-1">
                        <span className={cn('text-xs', config.color)}>{config.label}</span>
                        {task.progress !== undefined && task.progress > 0 && (
                          <span className="text-xs text-gray-400">{task.progress}%</span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* 进度条 */}
                  {isRunning && (
                    <div className="mt-2 h-1 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
                      <div
                        className="h-full bg-purple-500 rounded-full transition-all duration-500"
                        style={{ width: `${Math.min(task.progress || 10, 100)}%` }}
                      />
                    </div>
                  )}

                  {/* 错误信息 */}
                  {task.status === 'error' && task.error && (
                    <p className="mt-2 text-xs text-red-500">{task.error}</p>
                  )}
                </motion.div>
              );
            })}
          </AnimatePresence>
        </div>
      </ScrollArea>
    </div>
  );
}
