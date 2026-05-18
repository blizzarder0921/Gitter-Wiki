'use client';

import { useState, useCallback, useEffect } from 'react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
} from '@/components/ui/alert-dialog';
import { Loader2, Trash2, AlertTriangle, FolderOpen, Globe, FileArchive, Key, GitBranch, CheckCircle, XCircle } from 'lucide-react';
import { useI18n } from '@/lib/hooks/use-i18n';
import { toast } from 'sonner';
import { createLogger } from '@/lib/logger';
import { useSettingsStore } from '@/lib/store/settings';

const log = createLogger('GeneralSettings');

export function GeneralSettings() {
  const { t } = useI18n();
  const localStoragePath = useSettingsStore((state) => state.localStoragePath);
  const setLocalStoragePath = useSettingsStore((state) => state.setLocalStoragePath);
  const gitProxy = useSettingsStore((state) => state.gitProxy);
  const setGitProxy = useSettingsStore((state) => state.setGitProxy);
  const gitPath = useSettingsStore((state) => state.gitPath);
  const setGitPath = useSettingsStore((state) => state.setGitPath);
  const githubToken = useSettingsStore((state) => state.githubToken);
  const setGithubToken = useSettingsStore((state) => state.setGithubToken);
  const archiveFormat = useSettingsStore((state) => state.archiveFormat);
  const setArchiveFormat = useSettingsStore((state) => state.setArchiveFormat);
  const cloneMethod = useSettingsStore((state) => state.cloneMethod);
  const setCloneMethod = useSettingsStore((state) => state.setCloneMethod);
  const ghPath = useSettingsStore((state) => state.ghPath);
  const setGhPath = useSettingsStore((state) => state.setGhPath);
  const mirrorUrl = useSettingsStore((state) => state.mirrorUrl);
  const setMirrorUrl = useSettingsStore((state) => state.setMirrorUrl);

  const [showClearDialog, setShowClearDialog] = useState(false);
  const [confirmInput, setConfirmInput] = useState('');
  const [clearing, setClearing] = useState(false);

  const [selectingFolder, setSelectingFolder] = useState(false);

  /** 自动检测到的系统代理 */
  const [detectedProxy, setDetectedProxy] = useState<string | null>(null);

  /** 系统 Git 检测信息 */
  const [systemGit, setSystemGit] = useState<{ available: boolean; version: string | null; path: string | null } | null>(null);

  /** 自定义 Git 路径验证结果 */
  const [gitPathValidation, setGitPathValidation] = useState<{ valid: boolean; version?: string; error?: string } | null>(null);
  const [validatingGitPath, setValidatingGitPath] = useState(false);

  /** 克隆方式可用性检测 */
  const [cloneMethodStatus, setCloneMethodStatus] = useState<{
    ssh: boolean;
    sshKeyPath: string | null;
    ghCli: boolean;
    ghVersion: string | null;
  }>({ ssh: false, sshKeyPath: null, ghCli: false, ghVersion: null });

  /** 自定义 gh 路径验证结果 */
  const [ghPathValidation, setGhPathValidation] = useState<{ valid: boolean; version?: string; error?: string } | null>(null);
  const [validatingGhPath, setValidatingGhPath] = useState(false);

  useEffect(() => {
    fetch('/api/detect-proxy')
      .then((r) => r.json())
      .then((data) => setDetectedProxy(data.proxy))
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetch('/api/detect-git')
      .then((r) => r.json())
      .then((data) => setSystemGit(data))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const params = ghPath ? `?ghPath=${encodeURIComponent(ghPath)}` : '';
    fetch(`/api/detect-clone-methods${params}`)
      .then((r) => r.json())
      .then((data) => setCloneMethodStatus(data))
      .catch(() => {});
  }, [ghPath]);

  const confirmPhrase = t('settings.clearCacheConfirmPhrase');
  const isConfirmValid = confirmInput === confirmPhrase;

  /**
   * 清除缓存：清空前端存储（localStorage、sessionStorage、IndexedDB）
   * 和后端数据（SQLite 业务数据表、向量索引、graphify 缓存、临时文件）
   * localStorage 是设置的主存储（Zustand persist），必须清除否则数据会重新同步回来
   */
  const handleClearCache = useCallback(async () => {
    if (!isConfirmValid) return;
    setClearing(true);
    try {
      // 调用后端 API 清空所有业务数据表和缓存目录
      await fetch('/api/clear-cache', { method: 'POST' });

      // 清除 localStorage 中的设置数据（主存储，优先级最高）
      localStorage.removeItem('settings-storage');

      sessionStorage.clear();

      if (typeof indexedDB !== 'undefined') {
        const dbs = await indexedDB.databases();
        for (const db of dbs) {
          if (db.name) {
            indexedDB.deleteDatabase(db.name);
          }
        }
      }

      toast.success(t('settings.clearCacheSuccess'));

      setTimeout(() => {
        window.location.reload();
      }, 1000);
    } catch (error) {
      log.error('清除缓存失败:', error);
      toast.error(t('settings.clearCacheFailed'));
      setClearing(false);
    }
  }, [isConfirmValid, t]);

  const clearCacheItems =
    t('settings.clearCacheConfirmItems').split('、').length > 1
      ? t('settings.clearCacheConfirmItems').split('、')
      : t('settings.clearCacheConfirmItems').split(', ');

  return (
    <div className="flex flex-col gap-8">
      {/* 本地存储路径设置 */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="p-4 space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <FolderOpen className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold">{t('settings.localStoragePath')}</h3>
          </div>
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              {t('settings.localStoragePathDescription')}
            </p>
            <div className="flex gap-2 items-center">
              <Button
                variant="outline"
                size="sm"
                disabled={selectingFolder}
                onClick={async () => {
                  setSelectingFolder(true);
                  try {
                    const res = await fetch('/api/folder-dialog', { method: 'POST' });
                    const data = await res.json();
                    if (data.cancelled) {
                      return;
                    }
                    if (data.path) {
                      setLocalStoragePath(data.path);
                      toast.success(t('settings.saveSuccess'));
                    } else if (data.detail) {
                      toast.error(data.detail);
                    }
                  } catch (err) {
                    log.error('选择目录失败:', err);
                    toast.error(t('settings.folderSelectFailed'));
                  } finally {
                    setSelectingFolder(false);
                  }
                }}
              >
                {selectingFolder ? (
                  <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />
                ) : (
                  <FolderOpen className="w-4 h-4 mr-1.5" />
                )}
                {t('settings.selectFolder')}
              </Button>
              <Input
                placeholder={t('settings.localStoragePathPlaceholder')}
                value={localStoragePath}
                onChange={(e) => setLocalStoragePath(e.target.value)}
                className="flex-1 text-sm h-8"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Git 代理设置 */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="p-4 space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <Globe className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold">{t('settings.gitProxy')}</h3>
          </div>
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              {t('settings.gitProxyDescription')}
            </p>
            {detectedProxy && !gitProxy && (
              <p className="text-xs text-emerald-600 dark:text-emerald-400">
                {t('settings.systemProxyDetected')}{detectedProxy}
              </p>
            )}
            <div className="flex gap-2 items-center">
              <Input
                placeholder={t('settings.gitProxyPlaceholder')}
                value={gitProxy}
                onChange={(e) => setGitProxy(e.target.value)}
                className="flex-1 text-sm h-8"
              />
              {gitProxy && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 px-2 text-muted-foreground hover:text-foreground"
                  onClick={() => setGitProxy('')}
                >
                  {t('settings.clear')}
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Git 可执行文件路径设置 */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="p-4 space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <GitBranch className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold">{t('settings.gitPath')}</h3>
          </div>
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              {t('settings.gitPathDescription')}
            </p>
            {systemGit && systemGit.available && !gitPath && (
              <p className="text-xs text-emerald-600 dark:text-emerald-400">
                {t('settings.systemGitDetected')}{systemGit.version}
                {systemGit.path && <span className="text-muted-foreground ml-1">({systemGit.path})</span>}
              </p>
            )}
            {systemGit && !systemGit.available && !gitPath && (
              <p className="text-xs text-yellow-600 dark:text-yellow-400">
                {t('settings.systemGitNotFound')}
              </p>
            )}
            <div className="flex gap-2 items-center">
              <Input
                placeholder={t('settings.gitPathPlaceholder')}
                value={gitPath}
                onChange={(e) => {
                  setGitPath(e.target.value);
                  setGitPathValidation(null);
                }}
                className="flex-1 text-sm h-8"
              />
              <Button
                variant="outline"
                size="sm"
                className="h-8"
                disabled={!gitPath.trim() || validatingGitPath}
                onClick={async () => {
                  if (!gitPath.trim()) return;
                  setValidatingGitPath(true);
                  setGitPathValidation(null);
                  try {
                    const res = await fetch('/api/validate-git-path', {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ gitPath: gitPath.trim() }),
                    });
                    const data = await res.json();
                    setGitPathValidation(data);
                    if (data.valid) {
                      toast.success(`${t('settings.gitPathValid')} ${data.version}`);
                    } else {
                      toast.error(`${t('settings.gitPathInvalid')}${data.error}`);
                    }
                  } catch {
                    toast.error(t('settings.gitPathValidateFailed'));
                  } finally {
                    setValidatingGitPath(false);
                  }
                }}
              >
                {validatingGitPath ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  t('settings.gitPathValidate')
                )}
              </Button>
              {gitPath && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 px-2 text-muted-foreground hover:text-foreground"
                  onClick={() => {
                    setGitPath('');
                    setGitPathValidation(null);
                  }}
                >
                  {t('settings.clear')}
                </Button>
              )}
            </div>
            {gitPathValidation && (
              <div className={`flex items-center gap-1.5 text-xs ${gitPathValidation.valid ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                {gitPathValidation.valid ? (
                  <>
                    <CheckCircle className="w-3.5 h-3.5" />
                    <span>{gitPathValidation.version}</span>
                  </>
                ) : (
                  <>
                    <XCircle className="w-3.5 h-3.5" />
                    <span>{gitPathValidation.error}</span>
                  </>
                )}
              </div>
            )}

          </div>
        </div>
      </div>

      {/* 克隆方式设置 */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="p-4 space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <GitBranch className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold">{t('settings.cloneMethod')}</h3>
          </div>
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              {t('settings.cloneMethodDescription')}
            </p>
            <div className="flex gap-2 flex-wrap">
              <Button
                variant={cloneMethod === 'https' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setCloneMethod('https')}
              >
                HTTPS
              </Button>
              <Button
                variant={cloneMethod === 'ssh' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setCloneMethod('ssh')}
                disabled={!cloneMethodStatus.ssh}
              >
                SSH
                {!cloneMethodStatus.ssh && (
                  <span className="ml-1 text-xs opacity-60">({t('settings.cloneMethodNoKey')})</span>
                )}
              </Button>
              <Button
                variant={cloneMethod === 'gh_cli' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setCloneMethod('gh_cli')}
              >
                GitHub CLI
                {!cloneMethodStatus.ghCli && (
                  <span className="ml-1 text-xs opacity-60">({t('settings.cloneMethodNoGh')})</span>
                )}
              </Button>
              <div className="flex flex-col gap-2">
                <Button
                  variant={cloneMethod === 'mirror' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setCloneMethod('mirror')}
                >
                  {t('settings.cloneMethodMirror')}
                </Button>
                {cloneMethod === 'mirror' && (
                  <div className="space-y-2 p-2.5 rounded-lg bg-muted/50 border border-border">
                    <p className="text-xs text-muted-foreground">
                      {t('settings.cloneMethodMirrorNote')}
                    </p>
                    <Input
                      placeholder={t('settings.mirrorUrlPlaceholder')}
                      value={mirrorUrl}
                      onChange={(e) => setMirrorUrl(e.target.value)}
                      className="text-sm h-8"
                    />
                    <div className="flex flex-wrap gap-1.5">
                      {['https://ghproxy.com', 'https://mirror.ghproxy.com', 'https://gh-proxy.com', 'https://github.moeyy.xyz'].map((url) => (
                        <Button
                          key={url}
                          variant={mirrorUrl === url ? 'default' : 'outline'}
                          size="sm"
                          className="h-6 text-xs px-2"
                          onClick={() => setMirrorUrl(url)}
                        >
                          {url.replace('https://', '')}
                        </Button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
            {cloneMethod === 'https' && (
              <p className="text-xs text-muted-foreground">
                {t('settings.cloneMethodHttpsNote')}
              </p>
            )}
            {cloneMethod === 'ssh' && cloneMethodStatus.ssh && (
              <p className="text-xs text-emerald-600 dark:text-emerald-400">
                {t('settings.cloneMethodSshNote')}{cloneMethodStatus.sshKeyPath}
              </p>
            )}
            {cloneMethod === 'gh_cli' && (
              <div className="space-y-2">
                {cloneMethodStatus.ghCli ? (
                  <p className="text-xs text-emerald-600 dark:text-emerald-400">
                    {cloneMethodStatus.ghVersion}
                  </p>
                ) : (
                  <div className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
                    <AlertTriangle className="w-3.5 h-3.5" />
                    <span>{t('settings.cloneMethodGhNotDetected')}</span>
                  </div>
                )}
                <div className="flex gap-2 items-center">
                  <Input
                    placeholder={t('settings.ghPathPlaceholder')}
                    value={ghPath}
                    onChange={(e) => {
                      setGhPath(e.target.value);
                      setGhPathValidation(null);
                    }}
                    className="flex-1 text-sm h-8"
                  />
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8"
                    disabled={!ghPath.trim() || validatingGhPath}
                    onClick={async () => {
                      if (!ghPath.trim()) return;
                      setValidatingGhPath(true);
                      setGhPathValidation(null);
                      try {
                        const res = await fetch('/api/validate-gh-path', {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ ghPath: ghPath.trim() }),
                        });
                        const data = await res.json();
                        setGhPathValidation(data);
                      } catch {
                        toast.error(t('settings.ghPathValidateFailed'));
                      } finally {
                        setValidatingGhPath(false);
                      }
                    }}
                  >
                    {validatingGhPath ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : t('settings.ghPathValidate')}
                  </Button>
                  {ghPath && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-8 px-2 text-muted-foreground hover:text-foreground"
                      onClick={() => { setGhPath(''); setGhPathValidation(null); }}
                    >
                      {t('settings.clear')}
                    </Button>
                  )}
                </div>
                {ghPathValidation && (
                  <div className={`flex items-center gap-1.5 text-xs ${ghPathValidation.valid ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                    {ghPathValidation.valid ? (
                      <>
                        <CheckCircle className="w-3.5 h-3.5" />
                        <span>{ghPathValidation.version}</span>
                      </>
                    ) : (
                      <>
                        <XCircle className="w-3.5 h-3.5" />
                        <span>{ghPathValidation.error}</span>
                      </>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* GitHub Token 设置 */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="p-4 space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <Key className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold">GitHub Token</h3>
          </div>
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              用于调用 GitHub API 获取仓库信息（Releases、Issues 等）。未认证限额 60 次/小时，配置 Token 后提升至 5000 次/小时。
              可在 GitHub Settings → Developer settings → Personal access tokens 中生成，无需勾选任何权限（Fine-grained token 需勾选 Contents 只读）。
            </p>
            <div className="flex gap-2 items-center">
              <Input
                type="password"
                placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
                value={githubToken}
                onChange={(e) => setGithubToken(e.target.value)}
                className="flex-1 text-sm h-8"
              />
              {githubToken && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 px-2 text-muted-foreground hover:text-foreground"
                  onClick={() => setGithubToken('')}
                >
                  {t('settings.clear')}
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* 版本归档格式设置 */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="p-4 space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <FileArchive className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold">{t('settings.archiveFormat')}</h3>
          </div>
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              {t('settings.archiveFormatDescription')}
            </p>
            <div className="flex gap-2">
              <Button
                variant={archiveFormat === 'zip' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setArchiveFormat('zip')}
              >
                ZIP
              </Button>
              <Button
                variant={archiveFormat === '7z' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setArchiveFormat('7z')}
              >
                7-Zip
              </Button>
            </div>
            {archiveFormat === '7z' && (
              <p className="text-xs text-yellow-600 dark:text-yellow-400">
                {t('settings.archiveFormat7zNote')}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* 危险区域 - 清除缓存 */}
      <div className="relative rounded-xl border border-destructive/30 bg-destructive/[0.03] dark:bg-destructive/[0.06] overflow-hidden">
        <div
          className="absolute inset-0 opacity-[0.015] dark:opacity-[0.03] pointer-events-none"
          style={{
            backgroundImage: `repeating-linear-gradient(
              -45deg,
              transparent,
              transparent 10px,
              currentColor 10px,
              currentColor 11px
            )`,
          }}
        />

        <div className="relative p-4 space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-md bg-destructive/10 text-destructive">
              <AlertTriangle className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold text-destructive">{t('settings.dangerZone')}</h3>
          </div>

          <div className="flex items-center justify-between gap-4">
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium">{t('settings.clearCache')}</p>
              <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
                {t('settings.clearCacheDescription')}
              </p>
            </div>
            <Button
              variant="destructive"
              size="sm"
              className="shrink-0"
              onClick={() => {
                setConfirmInput('');
                setShowClearDialog(true);
              }}
            >
              <Trash2 className="w-3.5 h-3.5 mr-1.5" />
              {t('settings.clearCache')}
            </Button>
          </div>
        </div>
      </div>

      {/* 清除缓存确认对话框 */}
      <AlertDialog
        open={showClearDialog}
        onOpenChange={(open) => {
          if (!clearing) {
            setShowClearDialog(open);
            if (!open) setConfirmInput('');
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2 text-destructive">
              <AlertTriangle className="w-5 h-5" />
              {t('settings.clearCacheConfirmTitle')}
            </AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-3">
                <p>{t('settings.clearCacheConfirmDescription')}</p>
                <ul className="space-y-1.5 ml-1">
                  {clearCacheItems.map((item, i) => (
                    <li key={i} className="flex items-center gap-2 text-sm">
                      <span className="w-1.5 h-1.5 rounded-full bg-destructive/60 shrink-0" />
                      {item.trim()}
                    </li>
                  ))}
                </ul>
                <div className="pt-1">
                  <Label className="text-xs font-medium text-foreground">
                    {t('settings.clearCacheConfirmInput')}
                  </Label>
                  <Input
                    className="mt-1.5 h-9 text-sm"
                    placeholder={confirmPhrase}
                    value={confirmInput}
                    onChange={(e) => setConfirmInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && isConfirmValid) {
                        handleClearCache();
                      }
                    }}
                    autoFocus
                  />
                </div>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={clearing}>{t('common.cancel')}</AlertDialogCancel>
            <Button
              variant="destructive"
              disabled={!isConfirmValid || clearing}
              onClick={handleClearCache}
            >
              {clearing ? (
                <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />
              ) : (
                <Trash2 className="w-4 h-4 mr-1.5" />
              )}
              {t('settings.clearCacheButton')}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
