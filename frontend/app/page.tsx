'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { AnimatePresence } from 'motion/react';
import ShareDialog from '@/components/share/share-dialog';
import { Footer } from '@/components/home/footer';
import { ReadmeDialog } from '@/components/home/readme-dialog';
import { ConfirmDialog } from '@/components/home/confirm-dialog';
import { GraphDialog } from '@/components/home/graph-dialog';
import { ProjectDetailDialog } from '@/components/home/project-detail-dialog';
import { ProjectListPanel } from '@/components/home/project-list-panel';
import { RecentProjects } from '@/components/home/recent-projects';
import { ExtractResult } from '@/components/home/extract-result';
import { BatchExtractResult } from '@/components/home/batch-extract-result';
import { AddProjectPreview } from '@/components/home/add-project-preview';
import { Toolbar } from '@/components/home/toolbar';
import { HeroSection } from '@/components/home/hero-section';
import { useTranslate } from '@/lib/hooks/home/use-translate';
import { useProjects } from '@/lib/hooks/home/use-projects';
import { SettingsDialog } from '@/components/settings';
import { useTheme } from '@/lib/hooks/use-theme';
import { useForm } from '@/lib/hooks/home/use-form';
import { useI18n } from '@/lib/hooks/use-i18n';
import { useSettingsStore } from '@/lib/store/settings';
import { useGraph } from '@/lib/hooks/home/use-graph';
import { useGithubInfo } from '@/lib/hooks/home/use-github-info';
import { useExtract } from '@/lib/hooks/home/use-extract';
import { useClone } from '@/lib/hooks/home/use-clone';

function HomePage() {
  const { t } = useI18n?.() || { t: (key: string) => key };
  const { theme, setTheme } = useTheme();
  const router = useRouter();
  const { form, setForm, searchOpen, setSearchOpen, searchQuery, setSearchQuery, searchInputRef, searchButtonRef } = useForm();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { loading, previewInfo, setPreviewInfo, handleFetchGithubInfo } = useGithubInfo(form);
  const [themeOpen, setThemeOpen] = useState(false);
  const [expandedReadme, setExpandedReadme] = useState<{ title: string; content: string; githubUrl?: string } | null>(null);
  const { graphifyStatus, showGraphDialog, setShowGraphDialog, buildingGraph, checkGraphifyStatus, handleOpenGraph, handleBuildGraph } = useGraph();

  const {
    projects, loadProjects, projectListOpen, setProjectListOpen,
    projectSearch, setProjectSearch, detailProject, setDetailProject,
    versionArchives, loadingArchives, deleteConfirmId, setDeleteConfirmId,
    recentOpen, persistRecentOpen, fetchingResourcesId,
    shareOpen, setShareOpen, shareProject, setShareProject,
    toolbarRef, handleDeleteProject, confirmDeleteProject,
    openProjectDetail, handleRetryFetchResources,
    handleOpenFolder, loadVersionArchives,
  } = useProjects();

  const {
    cloningId, pullingId,
    addingProject, setAddingProject, addProjectStep,
    workflowProjectId, workflowStatus,
    handleAddProject, handleCloneProject,
    handlePullProject, handleUpdateAll,
  } = useClone({ loadProjects, previewInfo, setPreviewInfo, form, setForm });

  const {
    uploading, extractResult, setExtractResult,
    showOverwriteConfirm, setShowOverwriteConfirm,
    fileInputRef, dragOver, setDragOver,
    extracting, extractResults, setExtractResults,
    selectedRepos, setSelectedRepos,
    addingRepos, repoAddStatus, setRepoAddStatus,
    imageFile, setImageFile,
    handleFileUpload, handleConfirmAddFromZip,
    handleConfirmOverwrite, handleOverwriteFinal,
    handleSkipExtract, handleBatchExtract, handleBatchAdd,
  } = useExtract({ loadProjects, form, setForm, setPreviewInfo, addingProject, setAddingProject });

  const providersConfig = useSettingsStore((state) => state.providersConfig);
  const localStoragePath = useSettingsStore((state) => state.localStoragePath);
  const archiveFormat = useSettingsStore((state) => state.archiveFormat);
  const { translateModel, handleTranslateModelChange, translateTargetLang, translatingId, handleTranslateProject } = useTranslate(loadProjects, setDetailProject);

  return (
    <div className="min-h-[100dvh] w-full bg-gradient-to-b from-slate-50 to-slate-100 dark:from-slate-950 dark:to-slate-900 flex flex-col items-center p-4 pt-16 md:p-8 md:pt-16 overflow-x-hidden">
      {/* 右上角工具栏 */}
      <Toolbar
        translateModel={translateModel}
        onTranslateModelChange={handleTranslateModelChange}
        providersConfig={providersConfig}
        projectListOpen={projectListOpen}
        onProjectListToggle={() => { setProjectListOpen(!projectListOpen); if (projectListOpen) setProjectSearch(''); }}
        onSettingsOpen={() => setSettingsOpen(true)}
        onWikiNavigate={() => router.push('/wiki')}
        themeOpen={themeOpen}
        onThemeOpenChange={setThemeOpen}
        toolbarRef={toolbarRef}
        theme={theme}
        setTheme={setTheme}
      />

      <SettingsDialog open={settingsOpen} onOpenChange={(open) => setSettingsOpen(open)} />

      {/* README 弹窗 */}
      <ReadmeDialog readme={expandedReadme} open={!!expandedReadme} onOpenChange={() => setExpandedReadme(null)} />

      {/* 项目详情弹窗 */}
      <ProjectDetailDialog
        project={detailProject}
        open={!!detailProject}
        onOpenChange={() => setDetailProject(null)}
        versionArchives={versionArchives}
        loadingArchives={loadingArchives}
        cloningId={cloningId}
        pullingId={pullingId}
        translatingId={translatingId}
        fetchingResourcesId={fetchingResourcesId}
        onClone={handleCloneProject}
        onPull={handlePullProject}
        onTranslate={handleTranslateProject}
        onOpenGraph={handleOpenGraph}
        onOpenFolder={handleOpenFolder}
        onRetryFetchResources={handleRetryFetchResources}
        onShare={(p) => { setShareProject(p); setShareOpen(true); }}
        onSetDetailProject={setDetailProject}
      />

      {/* 知识图谱查看弹窗 */}
      <GraphDialog
        open={showGraphDialog}
        onOpenChange={setShowGraphDialog}
        project={detailProject}
        graphifyStatus={graphifyStatus}
        buildingGraph={buildingGraph}
        onBuildGraph={() => handleBuildGraph(detailProject!)}
      />

      {/* 右侧项目列表面板 */}
      <ProjectListPanel
        open={projectListOpen}
        projects={projects}
        projectSearch={projectSearch}
        onProjectSearchChange={setProjectSearch}
        onUpdateAll={handleUpdateAll}
        onOpenDetail={(p, e) => { openProjectDetail(p, e); setProjectListOpen(false); }}
        onClose={() => setProjectListOpen(false)}
        fetchingResourcesId={fetchingResourcesId}
        onRetryFetchResources={handleRetryFetchResources}
        onSetDetailProject={setDetailProject}
        onOpenGraph={handleOpenGraph}
        onOpenFolder={handleOpenFolder}
        onDeleteProject={handleDeleteProject}
        onPullProject={handlePullProject}
        onShareProject={(p) => { setShareProject(p); setShareOpen(true); }}
        pullingId={pullingId}
      />

      {/* Hero 区域：Logo + 输入框 */}
      <HeroSection
        form={form}
        onFormChange={(f) => { setForm(f); setPreviewInfo(null); }}
        loading={loading}
        extracting={extracting}
        onFetchGithubInfo={handleFetchGithubInfo}
        onBatchExtract={handleBatchExtract}
        uploading={uploading}
        dragOver={dragOver}
        onDragOverChange={setDragOver}
        onFileUpload={handleFileUpload}
        fileInputRef={fileInputRef}
        imageFile={imageFile}
        onImageFileChange={setImageFile}
      >
        {/* 压缩包解析结果 */}
        <AnimatePresence>
          {extractResult && (
            <ExtractResult
              result={extractResult}
              addingProject={addingProject}
              onConfirmAdd={handleConfirmAddFromZip}
              onConfirmOverwrite={handleConfirmOverwrite}
              onSkip={handleSkipExtract}
            />
          )}
        </AnimatePresence>

        {/* 批量提取结果展示 */}
        {extractResults && extractResults.repos.length > 0 && (
          <BatchExtractResult
            results={extractResults}
            selectedRepos={selectedRepos}
            onSelectedReposChange={setSelectedRepos}
            addingRepos={addingRepos}
            repoAddStatus={repoAddStatus}
            onBatchAdd={handleBatchAdd}
            onClose={() => { setExtractResults(null); setSelectedRepos(new Set()); }}
          />
        )}

        {/* 二次确认覆盖对话框 */}
        <ConfirmDialog
          variant="overwrite"
          open={showOverwriteConfirm}
          onOpenChange={setShowOverwriteConfirm}
          onConfirm={handleOverwriteFinal}
          loading={addingProject}
          detail={extractResult?.duplicate.existingProject?.local_path}
        />

        {/* 项目预览确认弹窗 */}
        <AnimatePresence>
          {previewInfo && (
            <AddProjectPreview
              previewInfo={previewInfo}
              addingProject={addingProject}
              addProjectStep={addProjectStep}
              workflowProjectId={workflowProjectId}
              workflowStatus={workflowStatus}
              localStoragePath={localStoragePath || ''}
              onAddProject={handleAddProject}
              onCancel={() => setPreviewInfo(null)}
            />
          )}
        </AnimatePresence>
      </HeroSection>

      {/* 删除项目确认对话框 */}
      <ConfirmDialog
        variant="delete"
        open={deleteConfirmId !== null}
        onOpenChange={(open) => { if (!open) setDeleteConfirmId(null); }}
        onConfirm={confirmDeleteProject}
      />

      {/* 最近项目 - 可折叠 */}
      <RecentProjects
        projects={projects}
        recentOpen={recentOpen}
        onRecentOpenChange={persistRecentOpen}
        searchOpen={searchOpen}
        onSearchOpenChange={setSearchOpen}
        searchQuery={searchQuery}
        onSearchQueryChange={setSearchQuery}
        searchInputRef={searchInputRef}
        searchButtonRef={searchButtonRef}
        onOpenDetail={openProjectDetail}
        fetchingResourcesId={fetchingResourcesId}
        onRetryFetchResources={handleRetryFetchResources}
        onSetDetailProject={setDetailProject}
        onOpenGraph={handleOpenGraph}
        onOpenFolder={handleOpenFolder}
        onDelete={handleDeleteProject}
        onPull={handlePullProject}
        pullingId={pullingId}
        onShare={(p) => { setShareProject(p); setShareOpen(true); }}
      />

      {/* 页脚 */}
      <Footer />

      {/* 分享文案弹窗 */}
      {shareProject && (
        <ShareDialog
          open={shareOpen}
          onOpenChange={setShareOpen}
          project={shareProject}
        />
      )}
    </div>
  );
}

export default HomePage;
