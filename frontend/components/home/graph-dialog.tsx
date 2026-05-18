'use client';

import { useState, useCallback } from 'react';
import { Network, Loader2, AlertTriangle, X } from 'lucide-react';
import { type Project } from '@/lib/types';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';

/**
 * GraphDialogProps - 知识图谱查看弹窗组件入参
 *
 * @property open - 弹窗是否可见
 * @property onOpenChange - 弹窗可见性变化回调
 * @property project - 当前查看的项目对象
 * @property graphifyStatus - 图谱状态信息（是否存在、HTML 文件、节点/边数量）
 * @property buildingGraph - 是否正在构建图谱
 * @property onBuildGraph - 点击构建图谱按钮的回调
 */
interface GraphDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  project: Project | null;
  graphifyStatus: {
    exists: boolean;
    hasHtml: boolean;
    nodeCount: number;
    edgeCount: number;
  } | null;
  buildingGraph: boolean;
  onBuildGraph: () => void;
}

/**
 * GraphDialog - 知识图谱查看弹窗
 *
 * 展示知识图谱的 iframe 视图，或引导用户构建图谱。
 * - 已构建：全屏 iframe 展示 HTML 图谱
 * - 未构建：空状态引导按钮
 * - 构建中：加载动画提示
 */
export function GraphDialog({
  open,
  onOpenChange,
  project,
  graphifyStatus,
  buildingGraph,
  onBuildGraph,
}: GraphDialogProps) {
  const [iframeLoading, setIframeLoading] = useState(true);
  const [iframeError, setIframeError] = useState(false);

  /** iframe 加载完成回调 */
  const handleIframeLoad = useCallback(() => {
    setIframeLoading(false);
    setIframeError(false);
  }, []);

  /** iframe 加载失败回调 */
  const handleIframeError = useCallback(() => {
    setIframeLoading(false);
    setIframeError(true);
  }, []);

  /** 弹窗关闭时重置状态 */
  const handleOpenChange = useCallback((nextOpen: boolean) => {
    if (!nextOpen) {
      setIframeLoading(true);
      setIframeError(false);
    }
    onOpenChange(nextOpen);
  }, [onOpenChange]);

  /** 图谱 iframe URL */
  const graphUrl = project ? `/api/graphify/${project.id}/graph` : '';

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        className="max-w-[95vw] w-full h-[90vh] flex flex-col p-0 gap-0 overflow-hidden"
        showCloseButton={false}
      >
        {/* 顶部标题栏 */}
        <DialogHeader className="px-6 py-4 border-b shrink-0">
          <div className="flex items-center justify-between">
            <DialogTitle className="flex items-center gap-2">
              <Network className="w-5 h-5 text-blue-500" />
              知识图谱
              {project && (
                <span className="text-gray-400 font-normal">
                  - {project.name}
                </span>
              )}
            </DialogTitle>
            <div className="flex items-center gap-3">
              {/* 节点/边统计 */}
              {graphifyStatus && graphifyStatus.nodeCount > 0 && (
                <span className="text-xs text-gray-400">
                  {graphifyStatus.nodeCount} 节点 · {graphifyStatus.edgeCount} 边
                </span>
              )}
              {/* 关闭按钮 */}
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => handleOpenChange(false)}
              >
                <X className="w-4 h-4" />
              </Button>
            </div>
          </div>
        </DialogHeader>

        {/* 内容区域 */}
        <div className="flex-1 min-h-0 relative">
          {project && graphifyStatus?.hasHtml ? (
            <>
              {/* iframe 加载中遮罩 */}
              {iframeLoading && !iframeError && (
                <div className="absolute inset-0 flex flex-col items-center justify-center bg-background/80 z-10">
                  <Loader2 className="w-8 h-8 animate-spin text-blue-500 mb-3" />
                  <p className="text-sm text-muted-foreground">正在加载知识图谱...</p>
                </div>
              )}
              {/* iframe 加载失败提示 */}
              {iframeError && (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 z-10">
                  <AlertTriangle className="w-10 h-10 text-yellow-500" />
                  <p className="text-sm text-muted-foreground">知识图谱加载失败</p>
                  <p className="text-xs text-gray-400">可能因网络问题导致外部资源加载失败，请检查网络连接后重试</p>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setIframeLoading(true);
                      setIframeError(false);
                    }}
                  >
                    重新加载
                  </Button>
                </div>
              )}
              {/* 图谱 iframe */}
              <iframe
                key={graphUrl}
                src={graphUrl}
                className="w-full h-full border-0"
                title="知识图谱"
                onLoad={handleIframeLoad}
                onError={handleIframeError}
              />
            </>
          ) : (
            /* 图谱未构建或可视化未生成：空状态 */
            <div className="flex flex-col items-center justify-center h-full gap-4 text-gray-400">
              <Network className="w-16 h-16 opacity-30" />
              {buildingGraph ? (
                /* 构建中状态 */
                <>
                  <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
                  <p className="text-sm">正在构建知识图谱，请稍候...</p>
                </>
              ) : graphifyStatus && graphifyStatus.exists && graphifyStatus.nodeCount > 0 ? (
                /* 图谱数据存在但可视化未生成 */
                <>
                  <p className="text-sm">图谱数据已存在（{graphifyStatus.nodeCount} 节点 · {graphifyStatus.edgeCount} 边），但可视化页面未生成</p>
                  <Button
                    onClick={() => onBuildGraph()}
                    disabled={buildingGraph}
                  >
                    <Network className="w-4 h-4 mr-2" />
                    重新构建可视化
                  </Button>
                  <p className="text-xs text-gray-300 dark:text-gray-500 mt-1">
                    大型项目的图谱可能需要较长时间生成可视化页面
                  </p>
                </>
              ) : (
                /* 未构建状态：引导构建 */
                <>
                  <p className="text-sm">知识图谱尚未构建</p>
                  <Button
                    onClick={() => onBuildGraph()}
                    disabled={buildingGraph}
                  >
                    <Network className="w-4 h-4 mr-2" />
                    构建知识图谱
                  </Button>
                  <p className="text-xs text-gray-300 dark:text-gray-500 mt-1">
                    构建需要源代码目录存在，如失败请重新克隆项目
                  </p>
                </>
              )}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
