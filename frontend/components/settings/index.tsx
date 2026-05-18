'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import {
  X,
  Trash2,
  Box,
  Settings,
  BookOpen,
  CheckCircle2,
  XCircle,
  Plus,
  FlaskConical,
  GitBranch,
  Database,
  Share2,
} from 'lucide-react';
import { useI18n } from '@/lib/hooks/use-i18n';
import { useSettingsStore } from '@/lib/store/settings';
import { toast } from 'sonner';
import { type ProviderId } from '@/lib/ai/providers';
import { PROVIDERS, MONO_LOGO_PROVIDERS } from '@/lib/ai/providers';
import { cn } from '@/lib/utils';
import { createCustomProviderSettings } from './utils';
import { ProviderList } from './provider-list';
import { ProviderConfigPanel } from './provider-config-panel';
import { GeneralSettings } from './general-settings';
import { WikiSettingsSection } from './wiki-settings-section';
import { ResearchSettings } from './research-settings-section';
import { EvolutionSettings } from './evolution-settings-section';
import { StorageSettings } from './storage-settings-section';
import { ShareSettingsSection } from './share-settings-section';
import { ModelEditDialog } from './model-edit-dialog';
import { AddProviderDialog, type NewProviderData } from './add-provider-dialog';
import type { SettingsSection, EditingModel } from '@/lib/types/settings';

interface SettingsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialSection?: SettingsSection;
}

/**
 * 系统设置对话框
 * 布局：左侧导航 + 中间提供商列表 + 右侧配置面板
 */
export function SettingsDialog({ open, onOpenChange, initialSection }: SettingsDialogProps) {
  const { t } = useI18n();

  const providerId = useSettingsStore((state) => state.providerId);
  const providersConfig = useSettingsStore((state) => state.providersConfig);

  const setModel = useSettingsStore((state) => state.setModel);
  const setProviderConfig = useSettingsStore((state) => state.setProviderConfig);
  const setProvidersConfig = useSettingsStore((state) => state.setProvidersConfig);

  const [activeSection, setActiveSection] = useState<SettingsSection>('providers');
  const [selectedProviderId, setSelectedProviderId] = useState<ProviderId>(providerId);

  useEffect(() => {
    if (open && initialSection) {
      setActiveSection(initialSection);
    }
  }, [open, initialSection]);

  const [editingModel, setEditingModel] = useState<EditingModel | null>(null);
  const [showModelDialog, setShowModelDialog] = useState(false);
  const [providerToDelete, setProviderToDelete] = useState<ProviderId | null>(null);
  const [showAddProviderDialog, setShowAddProviderDialog] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved' | 'error'>('idle');

  const [sidebarWidth, setSidebarWidth] = useState(192);
  const [providerListWidth, setProviderListWidth] = useState(192);
  const [isResizing, setIsResizing] = useState(false);
  const resizeRef = useRef<{
    target: 'sidebar' | 'providerList';
    startX: number;
    startWidth: number;
  } | null>(null);

  /**
   * 处理列宽拖拽开始
   */
  const handleResizeStart = useCallback(
    (e: React.MouseEvent, target: 'sidebar' | 'providerList') => {
      e.preventDefault();
      const startWidth = target === 'sidebar' ? sidebarWidth : providerListWidth;
      resizeRef.current = { target, startX: e.clientX, startWidth };
      setIsResizing(true);
    },
    [sidebarWidth, providerListWidth],
  );

  useEffect(() => {
    if (!isResizing) return;
    const handleMouseMove = (e: MouseEvent) => {
      if (!resizeRef.current) return;
      const { target, startX, startWidth } = resizeRef.current;
      const delta = e.clientX - startX;
      const newWidth = Math.max(120, Math.min(360, startWidth + delta));
      if (target === 'sidebar') setSidebarWidth(newWidth);
      else setProviderListWidth(newWidth);
    };
    const handleMouseUp = () => {
      resizeRef.current = null;
      setIsResizing(false);
    };
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'col-resize';
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
    };
  }, [isResizing]);

  /**
   * 提供商配置变更回调
   */
  const handleProviderConfigChange = (
    pid: ProviderId,
    apiKey: string,
    baseUrl: string,
    requiresApiKey: boolean,
  ) => {
    setProviderConfig(pid, { apiKey, baseUrl, requiresApiKey });
  };

  /**
   * 提供商配置保存回调
   */
  const handleProviderConfigSave = () => {
    setSaveStatus('saved');
    setTimeout(() => setSaveStatus('idle'), 2000);
  };

  const selectedProvider = providersConfig[selectedProviderId]
    ? {
        id: selectedProviderId,
        name: providersConfig[selectedProviderId].name,
        type: providersConfig[selectedProviderId].type,
        defaultBaseUrl: providersConfig[selectedProviderId].defaultBaseUrl,
        alternateBaseUrls: PROVIDERS[selectedProviderId]?.alternateBaseUrls,
        icon: providersConfig[selectedProviderId].icon,
        requiresApiKey: providersConfig[selectedProviderId].requiresApiKey,
        models: providersConfig[selectedProviderId].models,
      }
    : undefined;

  /**
   * 编辑模型
   */
  const handleEditModel = (pid: ProviderId, modelIndex: number) => {
    const allModels = providersConfig[pid]?.models || [];
    setEditingModel({ providerId: pid, modelIndex, model: { ...allModels[modelIndex] } });
    setShowModelDialog(true);
  };

  /**
   * 添加新模型
   */
  const handleAddModel = () => {
    setEditingModel({
      providerId: selectedProviderId,
      modelIndex: null,
      model: { id: '', name: '', capabilities: { streaming: true, tools: true, vision: false } },
    });
    setShowModelDialog(true);
  };

  /**
   * 删除模型
   * 所有模型均由用户手动管理，删除后直接移除
   */
  const handleDeleteModel = (pid: ProviderId, modelIndex: number) => {
    const currentModels = providersConfig[pid]?.models || [];
    const newModels = currentModels.filter((_, i) => i !== modelIndex);
    setProviderConfig(pid, { models: newModels });
  };

  /**
   * 自动保存模型
   */
  const handleAutoSaveModel = () => {
    if (!editingModel) return;
    const { providerId: pid, modelIndex, model } = editingModel;
    if (!model.id.trim()) return;
    const currentModels = providersConfig[pid]?.models || [];
    let newModels: typeof currentModels;
    let newModelIndex = modelIndex;
    if (modelIndex === null) {
      const existingIndex = currentModels.findIndex((m) => m.id === model.id);
      if (existingIndex >= 0) {
        newModels = [...currentModels];
        newModels[existingIndex] = model;
        newModelIndex = existingIndex;
      } else {
        newModels = [...currentModels, model];
        newModelIndex = newModels.length - 1;
      }
      setProviderConfig(pid, { models: newModels });
      setEditingModel({ ...editingModel, modelIndex: newModelIndex });
    } else {
      newModels = [...currentModels];
      newModels[modelIndex] = model;
      setProviderConfig(pid, { models: newModels });
    }
  };

  /**
   * 保存模型
   */
  const handleSaveModel = () => {
    if (!editingModel) return;
    const { providerId: pid, modelIndex, model } = editingModel;
    if (!model.id.trim()) {
      toast.error(t('settings.modelIdRequired'));
      return;
    }
    const currentModels = providersConfig[pid]?.models || [];
    let newModels: typeof currentModels;
    if (modelIndex === null) {
      newModels = [...currentModels, model];
    } else {
      newModels = [...currentModels];
      newModels[modelIndex] = model;
    }
    setProviderConfig(pid, { models: newModels });
    setShowModelDialog(false);
    setEditingModel(null);
  };

  /**
   * 添加自定义提供商
   */
  const handleAddProvider = (providerData: NewProviderData) => {
    if (!providerData.name.trim()) {
      toast.error(t('settings.providerNameRequired'));
      return;
    }
    const newProviderId = `custom-${Date.now()}` as ProviderId;
    const updatedConfig = {
      ...providersConfig,
      [newProviderId]: createCustomProviderSettings(providerData),
    };
    setProvidersConfig(updatedConfig);
    setShowAddProviderDialog(false);
    setSelectedProviderId(newProviderId);
  };

  /**
   * 删除提供商
   */
  const handleDeleteProvider = (pid: ProviderId) => {
    if (providersConfig[pid]?.isBuiltIn) {
      toast.error(t('settings.cannotDeleteBuiltIn'));
      return;
    }
    setProviderToDelete(pid);
  };

  /**
   * 确认删除提供商
   */
  const confirmDeleteProvider = () => {
    if (!providerToDelete) return;
    const pid = providerToDelete;
    const updatedConfig = { ...providersConfig };
    delete updatedConfig[pid];
    setProvidersConfig(updatedConfig);
    if (selectedProviderId === pid) {
      const firstRemainingPid = Object.keys(updatedConfig)[0] as ProviderId | undefined;
      setSelectedProviderId(firstRemainingPid || 'openai');
    }
    if (providerId === pid) {
      const firstRemainingPid = Object.keys(updatedConfig)[0] as ProviderId | undefined;
      const firstModel = firstRemainingPid
        ? updatedConfig[firstRemainingPid]?.models?.[0]?.id
        : undefined;
      if (firstRemainingPid && firstModel) {
        setModel(firstRemainingPid, firstModel);
      } else {
        setModel('openai' as ProviderId, 'gpt-5.4-mini');
      }
    }
    setProviderToDelete(null);
  };

  /**
   * 重置提供商为默认配置
   * 恢复系统默认的模型列表
   */
  const handleResetProvider = (pid: ProviderId) => {
    const provider = PROVIDERS[pid];
    if (!provider) return;
    setProviderConfig(pid, { models: [...provider.models] });
    toast.success(t('settings.resetSuccess'));
  };

  const allProviders = Object.entries(providersConfig).map(([id, config]) => ({
    id: id as ProviderId,
    name: config.name,
    type: config.type,
    defaultBaseUrl: config.defaultBaseUrl,
    icon: config.icon,
    requiresApiKey: config.requiresApiKey,
    models: config.models,
  }));

  /**
   * 获取右侧面板头部内容
   */
  const getHeaderContent = () => {
    switch (activeSection) {
      case 'general':
        return <h2 className="text-lg font-semibold">{t('settings.systemSettings')}</h2>;
      case 'providers':
        if (selectedProvider) {
          return (
            <>
              {selectedProvider.icon ? (
                <img
                  src={selectedProvider.icon}
                  alt={selectedProvider.name}
                  className={cn(
                    'w-8 h-8 rounded',
                    MONO_LOGO_PROVIDERS.has(selectedProvider.id) && 'dark:invert',
                  )}
                  onError={(e) => {
                    (e.target as HTMLImageElement).style.display = 'none';
                  }}
                />
              ) : (
                <Box className="h-8 w-8 text-muted-foreground" />
              )}
              <div>
                <h2 className="text-lg font-semibold">
                  {t(`settings.providerNames.${selectedProvider.id}`) !==
                  `settings.providerNames.${selectedProvider.id}`
                    ? t(`settings.providerNames.${selectedProvider.id}`)
                    : selectedProvider.name}
                </h2>
              </div>
            </>
          );
        }
        return <h2 className="text-lg font-semibold">{t('settings.providers')}</h2>;
      case 'wiki':
        return (
          <div className="flex items-center gap-3">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <BookOpen className="w-4 h-4" />
            </div>
            <h2 className="text-lg font-semibold">Wiki 引擎设置</h2>
          </div>
        );
      case 'research':
        return (
          <div className="flex items-center gap-3">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <FlaskConical className="w-4 h-4" />
            </div>
            <h2 className="text-lg font-semibold">深度研究设置</h2>
          </div>
        );
      case 'evolution':
        return (
          <div className="flex items-center gap-3">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <GitBranch className="w-4 h-4" />
            </div>
            <h2 className="text-lg font-semibold">自动进化设置</h2>
          </div>
        );
      case 'storage':
        return (
          <div className="flex items-center gap-3">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <Database className="w-4 h-4" />
            </div>
            <h2 className="text-lg font-semibold">存储设置</h2>
          </div>
        );
      case 'share':
        return (
          <div className="flex items-center gap-3">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <Share2 className="w-4 h-4" />
            </div>
            <h2 className="text-lg font-semibold">分享文案设置</h2>
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="h-[85vh] p-0 gap-0 block" showCloseButton={false}>
        <DialogTitle className="sr-only">{t('settings.title')}</DialogTitle>
        <DialogDescription className="sr-only">{t('settings.description')}</DialogDescription>
        <div className="flex h-full overflow-hidden">
          {/* 左侧导航栏 */}
          <div className="flex-shrink-0 bg-muted/30 p-3 space-y-1" style={{ width: sidebarWidth }}>
            <button
              onClick={() => setActiveSection('providers')}
              className={cn(
                'w-full flex items-center gap-3 px-3 py-2 text-sm rounded-lg transition-colors text-left min-w-0',
                activeSection === 'providers'
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'hover:bg-muted',
              )}
            >
              <Box className="h-4 w-4 shrink-0" />
              <span className="truncate">{t('settings.providers')}</span>
            </button>

            <button
              onClick={() => setActiveSection('general')}
              className={cn(
                'w-full flex items-center gap-3 px-3 py-2 text-sm rounded-lg transition-colors text-left min-w-0',
                activeSection === 'general'
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'hover:bg-muted',
              )}
            >
              <Settings className="h-4 w-4 shrink-0" />
              <span className="truncate">{t('settings.systemSettings')}</span>
            </button>

            <button
              onClick={() => setActiveSection('wiki')}
              className={cn(
                'w-full flex items-center gap-3 px-3 py-2 text-sm rounded-lg transition-colors text-left min-w-0',
                activeSection === 'wiki'
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'hover:bg-muted',
              )}
            >
              <BookOpen className="h-4 w-4 shrink-0" />
              <span className="truncate">Wiki 引擎</span>
            </button>

            <button
              onClick={() => setActiveSection('research')}
              className={cn(
                'w-full flex items-center gap-3 px-3 py-2 text-sm rounded-lg transition-colors text-left min-w-0',
                activeSection === 'research'
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'hover:bg-muted',
              )}
            >
              <FlaskConical className="h-4 w-4 shrink-0" />
              <span className="truncate">深度研究</span>
            </button>

            <button
              onClick={() => setActiveSection('evolution')}
              className={cn(
                'w-full flex items-center gap-3 px-3 py-2 text-sm rounded-lg transition-colors text-left min-w-0',
                activeSection === 'evolution'
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'hover:bg-muted',
              )}
            >
              <GitBranch className="h-4 w-4 shrink-0" />
              <span className="truncate">自动进化</span>
            </button>

            <button
              onClick={() => setActiveSection('storage')}
              className={cn(
                'w-full flex items-center gap-3 px-3 py-2 text-sm rounded-lg transition-colors text-left min-w-0',
                activeSection === 'storage'
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'hover:bg-muted',
              )}
            >
              <Database className="h-4 w-4 shrink-0" />
              <span className="truncate">存储</span>
            </button>

            <button
              onClick={() => setActiveSection('share')}
              className={cn(
                'w-full flex items-center gap-3 px-3 py-2 text-sm rounded-lg transition-colors text-left min-w-0',
                activeSection === 'share'
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'hover:bg-muted',
              )}
            >
              <Share2 className="h-4 w-4 shrink-0" />
              <span className="truncate">分享文案</span>
            </button>
          </div>

          {/* 侧边栏 resize 手柄 */}
          <div
            onMouseDown={(e) => handleResizeStart(e, 'sidebar')}
            className="flex-shrink-0 w-[5px] cursor-col-resize group flex justify-center"
          >
            <div className="w-px h-full bg-border group-hover:bg-primary/50 transition-colors" />
          </div>

          {/* 提供商列表（仅在 providers 区域显示） */}
          {activeSection === 'providers' && (
            <>
              <ProviderList
                providers={allProviders}
                selectedProviderId={selectedProviderId}
                onSelect={setSelectedProviderId}
                onAddProvider={() => setShowAddProviderDialog(true)}
                width={providerListWidth}
              />
              <div
                onMouseDown={(e) => handleResizeStart(e, 'providerList')}
                className="flex-shrink-0 w-[5px] cursor-col-resize group flex justify-center"
              >
                <div className="w-px h-full bg-border group-hover:bg-primary/50 transition-colors" />
              </div>
            </>
          )}

          {/* 右侧配置面板 */}
          <div className="flex-1 flex flex-col overflow-hidden min-w-0">
            {/* 头部 */}
            <div className="flex items-center justify-between p-5 border-b">
              <div className="flex items-center gap-3">{getHeaderContent()}</div>
              <div className="flex items-center gap-2">
                {activeSection === 'providers' &&
                  !providersConfig[selectedProviderId]?.isBuiltIn && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 px-2 text-destructive hover:text-destructive"
                      onClick={() => handleDeleteProvider(selectedProviderId)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                <Button variant="ghost" size="icon" onClick={() => onOpenChange(false)}>
                  <X className="h-4 w-4" />
                </Button>
              </div>
            </div>

            {/* 内容区 */}
            <div className="flex-1 overflow-y-auto p-5">
              {activeSection === 'general' && <GeneralSettings />}

              {activeSection === 'wiki' && <WikiSettingsSection />}
              {activeSection === 'research' && <ResearchSettings />}
              {activeSection === 'evolution' && <EvolutionSettings />}
              {activeSection === 'storage' && <StorageSettings />}
              {activeSection === 'share' && <ShareSettingsSection />}

              {activeSection === 'providers' && selectedProvider && (
                <ProviderConfigPanel
                  provider={selectedProvider}
                  initialApiKey={providersConfig[selectedProviderId]?.apiKey || ''}
                  initialBaseUrl={providersConfig[selectedProviderId]?.baseUrl || ''}
                  initialRequiresApiKey={providersConfig[selectedProviderId]?.requiresApiKey ?? true}
                  providersConfig={providersConfig}
                  onConfigChange={(apiKey, baseUrl, requiresApiKey) =>
                    handleProviderConfigChange(selectedProviderId, apiKey, baseUrl, requiresApiKey)
                  }
                  onSave={handleProviderConfigSave}
                  onEditModel={(modelIndex) => handleEditModel(selectedProviderId, modelIndex)}
                  onAddModel={handleAddModel}
                  onDeleteModel={(modelIndex) => handleDeleteModel(selectedProviderId, modelIndex)}
                  onResetToDefault={() => handleResetProvider(selectedProviderId)}
                  isBuiltIn={providersConfig[selectedProviderId]?.isBuiltIn ?? true}
                />
              )}

              {activeSection === 'providers' && !selectedProvider && (
                <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
                  {t('settings.selectProvider')}
                </div>
              )}
            </div>

            {/* 底部按钮栏 */}
            <div className="flex items-center justify-end gap-3 px-5 py-3 border-t bg-muted/30">
              {saveStatus === 'saved' && (
                <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
                  <CheckCircle2 className="h-4 w-4" />
                  <span>{t('settings.saveSuccess')}</span>
                </div>
              )}
              {saveStatus === 'error' && (
                <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
                  <XCircle className="h-4 w-4" />
                  <span>{t('settings.saveFailed')}</span>
                </div>
              )}
              <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
                {t('settings.close')}
              </Button>
            </div>
          </div>
        </div>
      </DialogContent>

      {/* 模型编辑对话框 */}
      {editingModel && (
        <ModelEditDialog
          open={showModelDialog}
          onOpenChange={setShowModelDialog}
          editingModel={editingModel}
          setEditingModel={setEditingModel}
          onSave={handleSaveModel}
          onAutoSave={handleAutoSaveModel}
          providerId={selectedProviderId}
          apiKey={providersConfig[selectedProviderId]?.apiKey || ''}
          baseUrl={providersConfig[selectedProviderId]?.baseUrl || providersConfig[selectedProviderId]?.defaultBaseUrl || ''}
          providerType={selectedProvider?.type}
          requiresApiKey={providersConfig[selectedProviderId]?.requiresApiKey}
        />
      )}

      {/* 添加提供商对话框 */}
      <AddProviderDialog
        open={showAddProviderDialog}
        onOpenChange={setShowAddProviderDialog}
        onAdd={handleAddProvider}
      />

      {/* 删除确认对话框 */}
      <AlertDialog open={!!providerToDelete} onOpenChange={() => setProviderToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('settings.deleteProvider')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('settings.deleteProviderConfirm')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('settings.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDeleteProvider}>
              {t('settings.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Dialog>
  );
}
