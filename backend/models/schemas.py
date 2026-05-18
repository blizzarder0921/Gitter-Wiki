from pydantic import BaseModel
from typing import Optional


class Project(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    readme: Optional[str] = None
    github_url: Optional[str] = None
    local_path: Optional[str] = None
    version_type: str = "none"
    latest_version: Optional[str] = None
    current_version: Optional[str] = None
    download_url: Optional[str] = None
    commit_sha: Optional[str] = None
    commit_date: Optional[str] = None
    sync_status: str = "synced"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_synced_at: Optional[str] = None


class CreateProjectInput(BaseModel):
    name: str
    description: Optional[str] = None
    readme: Optional[str] = None
    github_url: Optional[str] = None
    local_path: Optional[str] = None
    version_type: str = "none"
    latest_version: Optional[str] = None
    current_version: Optional[str] = None
    download_url: Optional[str] = None
    commit_sha: Optional[str] = None
    commit_date: Optional[str] = None
    sync_status: str = "synced"


class UpdateProjectInput(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    readme: Optional[str] = None
    local_path: Optional[str] = None
    version_type: Optional[str] = None
    latest_version: Optional[str] = None
    current_version: Optional[str] = None
    download_url: Optional[str] = None
    commit_sha: Optional[str] = None
    commit_date: Optional[str] = None
    sync_status: Optional[str] = None
    last_synced_at: Optional[str] = None


class VerifyModelInput(BaseModel):
    providerId: str
    modelId: str
    apiKey: Optional[str] = None
    baseUrl: Optional[str] = None
    providerType: Optional[str] = None
    requiresApiKey: bool = True


class TranslateInput(BaseModel):
    text: str
    targetLang: str = "zh-CN"
    providerId: Optional[str] = None
    modelId: Optional[str] = None
    apiKey: Optional[str] = None
    baseUrl: Optional[str] = None


class ShareGenerateInput(BaseModel):
    projectId: int
    style: Optional[str] = None
    agentPrompt: Optional[str] = None
    providerId: Optional[str] = None
    modelId: Optional[str] = None
    apiKey: Optional[str] = None
    baseUrl: Optional[str] = None


class GraphifyBuildInput(BaseModel):
    projectId: int


class OpenFolderInput(BaseModel):
    path: str


class MigrateProjectsInput(BaseModel):
    oldPath: str
    newPath: str


class WikiFsReadInput(BaseModel):
    path: Optional[str] = None
    projectId: Optional[int] = None


class WikiFsWriteInput(BaseModel):
    path: str
    content: str
    projectId: Optional[int] = None


class WikiFsDeleteInput(BaseModel):
    path: str
    projectId: Optional[int] = None
