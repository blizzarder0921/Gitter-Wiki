'use client';

import { useEffect } from 'react';
import {
  Sun,
  Moon,
  Monitor,
  Package,
  BookOpen,
  Settings,
} from 'lucide-react';
import { LanguageSwitcher } from '@/components/language-switcher';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { cn } from '@/lib/utils';
import { useI18n } from '@/lib/hooks/use-i18n';
import { type Theme } from '@/lib/hooks/use-theme';

/**
 * ToolbarProps - 工具栏组件入参
 *
 * @property translateModel - 当前选中的翻译模型标识（providerId:modelId）
 * @property onTranslateModelChange - 翻译模型变更回调
 * @property providersConfig - 提供商配置对象（含 models 列表）
 * @property projectListOpen - 项目列表面板是否展开
 * @property onProjectListToggle - 切换项目列表面板回调
 * @property onSettingsOpen - 打开设置弹窗回调
 * @property onWikiNavigate - 跳转 Wiki 全局入口回调
 * @property themeOpen - 主题下拉面板是否展开
 * @property onThemeOpenChange - 变更主题下拉面板展开状态
 * @property toolbarRef - 工具栏容器 ref，用于点击外部检测
 * @property theme - 当前主题：'light' | 'dark' | 'system'
 * @property setTheme - 设置主题回调
 */
interface ToolbarProps {
  translateModel: string;
  onTranslateModelChange: (value: string) => void;
  providersConfig: any;
  projectListOpen: boolean;
  onProjectListToggle: () => void;
  onSettingsOpen: () => void;
  onWikiNavigate: () => void;
  themeOpen: boolean;
  onThemeOpenChange: (open: boolean) => void;
  toolbarRef: React.RefObject<HTMLDivElement | null>;
  theme: string;
  setTheme: (theme: Theme) => void;
}

/**
 * Toolbar - 右上角固定工具栏
 *
 * 包含语言切换、翻译模型选择、主题切换、项目列表入口、
 * Wiki 全局入口、设置按钮。
 * 内部处理主题下拉面板的点击外部关闭逻辑。
 */
export function Toolbar({
  translateModel,
  onTranslateModelChange,
  providersConfig,
  projectListOpen,
  onProjectListToggle,
  onSettingsOpen,
  onWikiNavigate,
  themeOpen,
  onThemeOpenChange,
  toolbarRef,
  theme,
  setTheme,
}: ToolbarProps) {
  const { t } = useI18n();

  /* 主题下拉面板点击外部关闭 */
  useEffect(() => {
    if (!themeOpen) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (toolbarRef.current && !toolbarRef.current.contains(e.target as Node)) {
        onThemeOpenChange(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [themeOpen, onThemeOpenChange, toolbarRef]);

  return (
    <div
      ref={toolbarRef}
      className="fixed top-4 right-4 z-50 flex items-center gap-1 bg-white/60 dark:bg-gray-800/60 backdrop-blur-md px-2 py-1.5 rounded-full border border-gray-100/50 dark:border-gray-700/50 shadow-sm"
    >
      <LanguageSwitcher onOpen={() => onThemeOpenChange(false)} />

      <div className="w-[1px] h-4 bg-gray-200 dark:bg-gray-700" />

      {/* 翻译模型选择 */}
      <Select
        value={(() => {
          /* 仅当当前选中的提供商已配置 API Key 时才显示选中值，否则视为未选择 */
          if (!translateModel) return '';
          const [pid] = translateModel.split(':');
          const pConfig = providersConfig?.[pid as keyof typeof providersConfig];
          const isConfigured = pConfig && (pConfig.requiresApiKey ? pConfig.apiKey : pConfig.baseUrl);
          return isConfigured ? translateModel : '';
        })()}
        onValueChange={onTranslateModelChange}
      >
        <SelectTrigger className="h-7 w-[160px] text-xs border-0 bg-transparent shadow-none hover:bg-white/50 dark:hover:bg-gray-700/50">
          <SelectValue placeholder={t('toolbar.selectModel')}>
            {(() => {
              if (!translateModel) return t('toolbar.selectModel');
              const [pid, ...modelParts] = translateModel.split(':');
              const modelId = modelParts.join(':');
              const pConfig = providersConfig?.[pid as keyof typeof providersConfig];
              const isConfigured = pConfig && (pConfig.requiresApiKey ? pConfig.apiKey : pConfig.baseUrl);
              if (!isConfigured) return t('toolbar.selectModel');
              const model = pConfig.models.find((m: { id: string }) => m.id === modelId);
              return model?.name || modelId;
            })()}
          </SelectValue>
        </SelectTrigger>
        <SelectContent position="popper" align="end" sideOffset={4}>
          {providersConfig && Object.entries(providersConfig)
            .filter(([, pConfig]: [string, any]) =>
              // 过滤未配置 API Key 的提供商
              pConfig.requiresApiKey
                ? pConfig.apiKey
                : pConfig.baseUrl
            )
            .map(([pid, pConfig]: [string, any]) =>
              pConfig.models.map((model: { id: string; name: string }) => (
                <SelectItem key={`${pid}:${model.id}`} value={`${pid}:${model.id}`}>
                  {model.name}
                </SelectItem>
              ))
            )}
        </SelectContent>
      </Select>

      <div className="w-[1px] h-4 bg-gray-200 dark:bg-gray-700" />

      {/* 主题选择 */}
      <div className="relative">
        <button
          onClick={() => onThemeOpenChange(!themeOpen)}
          className="p-2 rounded-full text-gray-400 dark:text-gray-500 hover:bg-white dark:hover:bg-gray-700 hover:text-gray-800 dark:hover:text-gray-200 hover:shadow-sm transition-all"
        >
          {theme === 'light' && <Sun className="w-4 h-4" />}
          {theme === 'dark' && <Moon className="w-4 h-4" />}
          {theme === 'system' && <Monitor className="w-4 h-4" />}
        </button>
        {themeOpen && (
          <div className="absolute top-full mt-2 right-0 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg overflow-hidden z-50 min-w-[140px]">
            {[
              { value: 'light', icon: Sun, label: '浅色' },
              { value: 'dark', icon: Moon, label: '深色' },
              { value: 'system', icon: Monitor, label: '跟随系统' },
            ].map(({ value, icon: Icon, label }) => (
              <button
                key={value}
                onClick={() => { setTheme(value as any); onThemeOpenChange(false); }}
                className={cn(
                  'w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors flex items-center gap-2',
                  theme === value && 'bg-purple-50 dark:bg-purple-900/20 text-purple-600 dark:text-purple-400',
                )}
              >
                <Icon className="w-4 h-4" /> {label}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="w-[1px] h-4 bg-gray-200 dark:bg-gray-700" />

      {/* 项目列表按钮 */}
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            onClick={onProjectListToggle}
            className={cn(
              'p-2 rounded-full transition-all',
              projectListOpen
                ? 'bg-purple-100 dark:bg-purple-900/40 text-purple-600 dark:text-purple-400'
                : 'text-gray-400 dark:text-gray-500 hover:bg-white dark:hover:bg-gray-700 hover:text-gray-800 dark:hover:text-gray-200 hover:shadow-sm',
            )}
          >
            <Package className="w-4 h-4" />
          </button>
        </TooltipTrigger>
        <TooltipContent side="bottom">项目列表</TooltipContent>
      </Tooltip>

      <div className="w-[1px] h-4 bg-gray-200 dark:bg-gray-700" />

      {/* Wiki 知识库入口按钮 */}
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            onClick={onWikiNavigate}
            className="p-2 rounded-full text-gray-400 dark:text-gray-500 hover:bg-white dark:hover:bg-gray-700 hover:text-purple-600 dark:hover:text-purple-400 hover:shadow-sm transition-all"
          >
            <BookOpen className="w-4 h-4" />
          </button>
        </TooltipTrigger>
        <TooltipContent side="bottom">{t('toolbar.wikiTooltip')}</TooltipContent>
      </Tooltip>

      <div className="w-[1px] h-4 bg-gray-200 dark:bg-gray-700" />

      {/* 设置按钮 */}
      <button
        onClick={onSettingsOpen}
        className="p-2 rounded-full text-gray-400 dark:text-gray-500 hover:bg-white dark:hover:bg-gray-700 hover:text-gray-800 dark:hover:text-gray-200 hover:shadow-sm transition-all group"
      >
        <Settings className="w-4 h-4 group-hover:rotate-90 transition-transform duration-500" />
      </button>
    </div>
  );
}
