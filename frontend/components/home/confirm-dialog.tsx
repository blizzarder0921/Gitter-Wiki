'use client';

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { AlertCircle, Loader2 } from 'lucide-react';

/**
 * 确认弹窗组件的属性
 */
interface ConfirmDialogProps {
  /** 弹窗变体：overwrite（覆盖确认）或 delete（删除确认） */
  variant: 'overwrite' | 'delete';
  /** 弹窗是否打开 */
  open: boolean;
  /** 弹窗开关状态变化的回调 */
  onOpenChange: (open: boolean) => void;
  /** 确认操作的回调 */
  onConfirm: () => void;
  /** 是否处于加载中状态（仅 overwrite 变体使用） */
  loading?: boolean;
  /** 额外展示的详情文本（仅 overwrite 变体使用，如文件路径） */
  detail?: string | null;
}

/**
 * 通用确认弹窗组件
 * 支持「覆盖确认」和「删除确认」两种变体
 */
export function ConfirmDialog({ variant, open, onOpenChange, onConfirm, loading, detail }: ConfirmDialogProps) {
  const isOverwrite = variant === 'overwrite';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-red-600 dark:text-red-400">
            <AlertCircle className="w-5 h-5" />
            {isOverwrite ? '确认覆盖' : '确认删除'}
          </DialogTitle>
          <DialogDescription>
            {isOverwrite
              ? '此操作将删除本地现有文件夹，并用压缩包内容替换。此操作不可恢复！'
              : '确定要删除此项目吗？此操作不可撤销。'}
          </DialogDescription>
        </DialogHeader>
        {isOverwrite && detail && (
          <div className="rounded-lg bg-red-50 dark:bg-red-900/20 p-3 text-sm text-red-700 dark:text-red-300 font-mono break-all">
            {detail}
          </div>
        )}
        <div className="flex justify-end gap-2 mt-2">
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button size="sm" variant="destructive" onClick={onConfirm} disabled={loading}>
            {loading ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : null}
            {isOverwrite ? '确认覆盖' : '确认删除'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
