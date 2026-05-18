export type OutputLanguage =
  | 'auto'
  | 'Chinese'
  | 'English'
  | 'Japanese'
  | 'Korean'
  | 'French'
  | 'German'
  | 'Spanish'
  | 'Portuguese'
  | 'Italian'
  | 'Russian'
  | 'Arabic'
  | 'Persian'
  | 'Hindi'
  | 'Turkish'
  | 'Dutch'
  | 'Polish'
  | 'Swedish'
  | 'Indonesian'
  | 'Thai'
  | 'Ukrainian'
  | 'Vietnamese'
  | 'Traditional Chinese'

export type WikiView =
  | 'chat'
  | 'sources'
  | 'graph'
  | 'lint'
  | 'review'
  | 'research'
  | 'health'
  | 'settings'

export interface FileNode {
  name: string
  path: string
  is_dir: boolean
  children?: FileNode[]
}

export type ReviewItemType =
  | 'contradiction'
  | 'duplicate'
  | 'missing-page'
  | 'confirm'
  | 'suggestion'

export interface ReviewItem {
  id: string
  type: ReviewItemType
  content: string
  action?: string
  resolved: boolean
  createdAt: string
}

export type ResearchTaskStatus =
  | 'queued'
  | 'searching'
  | 'synthesizing'
  | 'saving'
  | 'done'
  | 'error'

export interface ResearchTask {
  id: string
  topic: string
  status: ResearchTaskStatus
  progress: number
  error?: string
  createdAt: number
  updatedAt: number
}

export interface IngestProgress {
  status: 'running' | 'completed' | 'error'
  totalFiles: number
  processedFiles: number
  currentPage: number
  currentFile: string | null
  errorMessage: string | null
}

export interface HealthScore {
  score: number
  nodeCount: number
  edgeCount: number
  isolatedPages: number
  brokenLinks: number
  outdatedConcepts: number
}

export interface LintResult {
  severity: 'error' | 'warning' | 'info'
  message: string
  page?: string
  detail?: string
}

export interface GraphNode {
  id: string
  label: string
  type?: string
  path?: string
  linkCount: number
  community: number
  projectSources?: string[]
}

export interface GraphEdge {
  source: string
  target: string
  weight: number
}

export interface GraphCommunity {
  id: number
  nodeCount: number
  topNodes: string[]
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
  communities: GraphCommunity[]
  sourceToName?: Record<string, string>
}

export type GraphInsightType =
  | 'surprising-connection'
  | 'knowledge-gap'
  | 'hub-node'

export interface GraphInsight {
  type: GraphInsightType
  description: string
  relatedPages: string[]
}
