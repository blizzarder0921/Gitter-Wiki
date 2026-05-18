'use client';

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { rehypeStripReactIgnoredAttrs } from '@/lib/utils/rehype-strip-attrs';
import { rewriteReadmeImagePaths } from '@/lib/utils/readme';

/**
 * README 弹窗组件的数据结构
 */
interface ReadmeDialogProps {
  /** README 数据，包含标题、内容和可选的 GitHub URL */
  readme: { title: string; content: string; githubUrl?: string } | null;
  /** 弹窗是否打开 */
  open: boolean;
  /** 弹窗开关状态变化的回调 */
  onOpenChange: (open: boolean) => void;
}

/**
 * README 内容预览弹窗
 * 以 Markdown 渲染项目 README，支持图片路径重写
 */
export function ReadmeDialog({ readme, open, onOpenChange }: ReadmeDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{readme?.title}</DialogTitle>
          <DialogDescription>README 内容</DialogDescription>
        </DialogHeader>
        <div className="prose prose-sm dark:prose-invert max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw, rehypeStripReactIgnoredAttrs]}>
            {rewriteReadmeImagePaths(readme?.content || '', readme?.githubUrl)}
          </ReactMarkdown>
        </div>
      </DialogContent>
    </Dialog>
  );
}
