'use client';

import { motion } from 'motion/react';
import {
  Github,
  Link,
  Loader2,
  FileArchive,
  FileText,
  X,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { InputGroup, InputGroupInput } from '@/components/ui/input-group';
import { cn } from '@/lib/utils';

/** HeroSection 组件的 Props 类型定义 */
interface HeroSectionProps {
  /** 表单数据，包含 githubUrl */
  form: { githubUrl: string };
  /** 表单变更回调 */
  onFormChange: (form: { githubUrl: string }) => void;
  /** 是否正在加载 GitHub 信息 */
  loading: boolean;
  /** 是否正在提取 */
  extracting: boolean;
  /** 获取 GitHub 信息回调 */
  onFetchGithubInfo: () => void;
  /** 批量提取回调（文章链接/图片识别） */
  onBatchExtract: () => void;
  /** 是否正在上传压缩包 */
  uploading: boolean;
  /** 是否处于拖拽悬停状态 */
  dragOver: boolean;
  /** 拖拽悬停状态变更回调 */
  onDragOverChange: (v: boolean) => void;
  /** 文件上传处理回调 */
  onFileUpload: (file: File) => void;
  /** 隐藏的文件输入框引用 */
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  /** 当前预览的图片文件 */
  imageFile: File | null;
  /** 图片文件变更回调 */
  onImageFileChange: (file: File | null) => void;
  /** 子内容插槽，用于渲染提取结果、确认对话框等 */
  children?: React.ReactNode;
}

/**
 * Hero 区域组件
 * 包含 Logo、GitHub URL 输入框、拖拽上传区域及子内容插槽
 */
export function HeroSection({
  form,
  onFormChange,
  loading,
  extracting,
  onFetchGithubInfo,
  onBatchExtract,
  uploading,
  dragOver,
  onDragOverChange,
  onFileUpload,
  fileInputRef,
  imageFile,
  onImageFileChange,
  children,
}: HeroSectionProps) {
  /** 判断按钮文字：非 GitHub 的 http 链接显示"开始提取" */
  const buttonText =
    form.githubUrl.trim() &&
    !form.githubUrl.includes('github.com') &&
    form.githubUrl.trim().startsWith('http')
      ? '开始提取'
      : '获取信息';

  /** 处理按钮点击：根据 URL 类型决定调用哪个回调 */
  const handleButtonClick = () => {
    const input = form.githubUrl.trim();
    if (input && !input.includes('github.com') && input.startsWith('http')) {
      onBatchExtract();
    } else {
      onFetchGithubInfo();
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, ease: 'easeOut' }}
      className="relative z-20 w-full max-w-[800px] flex flex-col items-center mt-[10vh]"
    >
      {/* 背景装饰渐变光斑 */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none -z-10">
        <div
          className="absolute top-0 left-1/4 w-96 h-96 bg-blue-500/10 rounded-full blur-3xl animate-pulse"
          style={{ animationDuration: '4s' }}
        />
        <div
          className="absolute bottom-0 right-1/4 w-96 h-96 bg-purple-500/10 rounded-full blur-3xl animate-pulse"
          style={{ animationDuration: '6s' }}
        />
      </div>

      {/* Logo */}
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 0.1, type: 'spring', stiffness: 200, damping: 20 }}
        className="flex items-center gap-3 mb-2"
      >
        <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-purple-500 to-blue-500 flex items-center justify-center shadow-lg">
          <Github className="w-7 h-7 text-white" />
        </div>
        <h1 className="text-4xl font-bold bg-gradient-to-r from-purple-600 to-blue-600 bg-clip-text text-transparent">
          Gitter
        </h1>
      </motion.div>

      <motion.p
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.25 }}
        className="text-sm text-muted-foreground/60 mb-8"
      >
        GitHub 项目本地管理工具
      </motion.p>

      {/* GitHub URL 输入框 */}
      <motion.div
        initial={{ opacity: 0, scale: 0.97 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 0.35 }}
        className="w-full"
      >
        <div className="w-full rounded-2xl border border-border/60 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-xl shadow-black/[0.03] dark:shadow-black/20 p-4">
          <div className="flex items-center gap-2 mb-4">
            <Link className="w-4 h-4 text-purple-500" />
            <span className="text-sm font-medium">添加新项目</span>
          </div>
          <div className="flex gap-2">
            <InputGroup className="flex-1">
              <InputGroupInput
                placeholder="粘贴 GitHub 地址或文章链接"
                value={form.githubUrl}
                onChange={(e) => {
                  onFormChange({ githubUrl: e.target.value });
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleButtonClick();
                }}
              />
            </InputGroup>
            <Button
              onClick={handleButtonClick}
              disabled={!form.githubUrl.trim() || loading || extracting}
              className="shrink-0 !text-white"
            >
              {loading || extracting ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                buttonText
              )}
            </Button>
          </div>

          {/* 分隔线：或者 */}
          <div className="flex items-center gap-3 my-4">
            <div className="flex-1 h-px bg-gray-200 dark:bg-gray-700" />
            <span className="text-xs text-gray-400 dark:text-gray-500">或者</span>
            <div className="flex-1 h-px bg-gray-200 dark:bg-gray-700" />
          </div>

          {/* 压缩包上传区域 */}
          <div
            className={cn(
              'relative rounded-xl border-2 border-dashed transition-colors cursor-pointer',
              dragOver
                ? 'border-purple-400 bg-purple-50 dark:bg-purple-900/20'
                : 'border-gray-200 dark:border-gray-700 hover:border-purple-300 dark:hover:border-purple-600 hover:bg-gray-50 dark:hover:bg-gray-800/50',
              uploading && 'pointer-events-none opacity-60',
            )}
            onDragOver={(e) => {
              e.preventDefault();
              onDragOverChange(true);
            }}
            onDragLeave={() => onDragOverChange(false)}
            onDrop={(e) => {
              e.preventDefault();
              onDragOverChange(false);
              const file = e.dataTransfer.files[0];
              if (file) onFileUpload(file);
            }}
            onClick={() => fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".zip,.7z,.png,.jpg,.jpeg"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) onFileUpload(file);
                e.target.value = '';
              }}
            />
            <div className="flex flex-col items-center justify-center py-6 px-4">
              {uploading ? (
                <>
                  <Loader2 className="w-8 h-8 text-purple-500 animate-spin mb-2" />
                  <span className="text-sm text-gray-500 dark:text-gray-400">
                    正在解析压缩包...
                  </span>
                </>
              ) : (
                <>
                  <FileArchive className="w-8 h-8 text-gray-300 dark:text-gray-600 mb-2" />
                  <span className="text-sm text-gray-500 dark:text-gray-400 mb-1">
                    拖拽压缩包到此处，或{' '}
                    <span className="text-purple-500 hover:text-purple-600">点击上传</span>
                  </span>
                  <span className="text-xs text-gray-400 dark:text-gray-500">
                    支持 .zip .7z .png .jpg .jpeg 格式
                  </span>
                </>
              )}
            </div>
          </div>

          {/* 图片预览和提取按钮 */}
          {imageFile && (
            <div className="mt-3 p-3 rounded-xl bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800">
              <div className="flex items-center gap-2 mb-2">
                <FileText className="w-4 h-4 text-blue-500" />
                <span className="text-sm font-medium">{imageFile.name}</span>
                <button
                  onClick={() => onImageFileChange(null)}
                  className="ml-auto p-1 rounded text-gray-400 hover:text-red-500 transition-colors"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
              <Button
                size="sm"
                onClick={onBatchExtract}
                disabled={extracting}
                className="w-full"
              >
                {extracting ? (
                  <Loader2 className="w-4 h-4 animate-spin mr-1" />
                ) : null}
                {extracting ? '正在识别...' : '从图片中提取 GitHub 链接'}
              </Button>
            </div>
          )}

          {/* 子内容插槽：提取结果、批量结果、确认对话框、预览 */}
          {children}
        </div>
      </motion.div>
    </motion.div>
  );
}
