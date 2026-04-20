export type ObjectType =
  | 'system'
  | 'actor'
  | 'external_system'
  | 'group'
  | 'app'
  | 'store'
  | 'component'

export type ObjectScope = 'internal' | 'external'

export type ObjectStatus = 'live' | 'future' | 'deprecated' | 'removed'

export type ConnectionDirection = 'unidirectional' | 'bidirectional'

export type EdgeShape = 'curved' | 'straight' | 'step' | 'smoothstep'

export type DiagramType =
  | 'system_landscape'
  | 'system_context'
  | 'container'
  | 'component'
  | 'custom'

export interface ModelObject {
  id: string
  name: string
  type: ObjectType
  scope: ObjectScope
  status: ObjectStatus
  c4_level: string
  description: string | null
  icon: string | null
  parent_id: string | null
  technology: string[] | null
  tags: string[] | null
  owner_team: string | null
  external_links: Record<string, string> | null
  metadata: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface Connection {
  id: string
  source_id: string
  target_id: string
  label: string | null
  protocol: string | null
  direction: ConnectionDirection
  tags: string[] | null
  source_handle: string | null
  target_handle: string | null
  shape: EdgeShape
  label_size: number
  via_object_ids: string[] | null
  created_at: string
  updated_at: string
}

export interface ConnectionUpdate {
  label?: string | null
  protocol?: string | null
  direction?: ConnectionDirection
  tags?: string[] | null
  shape?: EdgeShape
  label_size?: number
  via_object_ids?: string[] | null
}

export interface Diagram {
  id: string
  name: string
  type: DiagramType
  description: string | null
  scope_object_id: string | null
  settings: Record<string, unknown> | null
  pinned: boolean
  draft_id: string | null
  created_at: string
  updated_at: string
}

export interface DiagramObject {
  id: string
  diagram_id: string
  object_id: string
  position_x: number
  position_y: number
  width: number | null
  height: number | null
}

export interface ObjectCreate {
  name: string
  type: ObjectType
  scope?: ObjectScope
  status?: ObjectStatus
  description?: string | null
  icon?: string | null
  parent_id?: string | null
  technology?: string[] | null
  tags?: string[] | null
  owner_team?: string | null
  metadata?: Record<string, unknown> | null
}

export interface ObjectUpdate {
  name?: string
  type?: ObjectType
  scope?: ObjectScope
  status?: ObjectStatus
  description?: string | null
  icon?: string | null
  parent_id?: string | null
  technology?: string[] | null
  tags?: string[] | null
  owner_team?: string | null
  metadata?: Record<string, unknown> | null
}

export interface ConnectionCreate {
  source_id: string
  target_id: string
  label?: string | null
  protocol?: string | null
  direction?: ConnectionDirection
  tags?: string[] | null
  source_handle?: string | null
  target_handle?: string | null
}

export type CommentTargetType = 'object' | 'connection' | 'diagram'
export type CommentType = 'question' | 'inaccuracy' | 'idea' | 'note'

export interface Comment {
  id: string
  target_type: CommentTargetType
  target_id: string
  comment_type: CommentType
  body: string
  author_id: string | null
  author: { id: string; email: string } | null
  resolved: boolean
  position_x: number | null
  position_y: number | null
  created_at: string
  updated_at: string
}

export interface CommentCreate {
  target_type: CommentTargetType
  target_id: string
  comment_type?: CommentType
  body: string
  position_x?: number | null
  position_y?: number | null
}

export interface CommentUpdate {
  comment_type?: CommentType
  body?: string
  resolved?: boolean
  position_x?: number | null
  position_y?: number | null
}

export interface FlowStep {
  id: string
  connection_id: string
  branch: string | null
  note: string | null
}

export interface Flow {
  id: string
  diagram_id: string
  name: string
  description: string | null
  steps: FlowStep[]
  created_at: string
  updated_at: string
}

export interface FlowCreate {
  name: string
  description?: string | null
  steps?: FlowStep[]
}

export interface FlowUpdate {
  name?: string
  description?: string | null
  steps?: FlowStep[]
}

export type DraftStatus = 'open' | 'merged' | 'discarded'

export interface DraftDiagram {
  id: string
  draft_id: string
  source_diagram_id: string
  forked_diagram_id: string
  source_diagram_name: string | null
  forked_diagram_name: string | null
  created_at: string
}

export interface Draft {
  id: string
  name: string
  description: string | null
  status: DraftStatus
  author_id: string | null
  diagrams: DraftDiagram[]
  created_at: string
  updated_at: string
}

export interface DraftCreate {
  name: string
  description?: string | null
}

export interface DraftFromDiagram {
  name: string
  description?: string | null
}

export type DraftDiffStatusSource = 'unchanged' | 'modified' | 'deleted'
export type DraftDiffStatusFork = 'unchanged' | 'modified' | 'new'

export interface DraftDiffSummary {
  added_objects: number
  modified_objects: number
  deleted_objects: number
  added_connections: number
  modified_connections: number
  deleted_connections: number
  moved_objects: number
  resized_objects: number
}

export interface PerDiagramDiffEntry {
  source_diagram_id: string
  forked_diagram_id: string
  source_diagram_name: string | null
  forked_diagram_name: string | null
  source_objects: Record<string, DraftDiffStatusSource>
  fork_objects: Record<string, DraftDiffStatusFork>
  source_connections: Record<string, DraftDiffStatusSource>
  fork_connections: Record<string, DraftDiffStatusFork>
  moved_on_fork: string[]
  resized_on_fork: string[]
  object_names: Record<string, string>
  summary: DraftDiffSummary
}

export interface DraftDiff {
  total_summary: DraftDiffSummary
  per_diagram: PerDiagramDiffEntry[]
}

export type ApiKeyPermission = 'read' | 'write' | 'admin'

export interface ApiKey {
  id: string
  name: string
  key_prefix: string
  permissions: ApiKeyPermission[]
  expires_at: string | null
  last_used_at: string | null
  revoked_at: string | null
  created_at: string
}

export interface ApiKeyWithSecret extends ApiKey {
  secret: string
}

export interface ApiKeyCreate {
  name: string
  permissions: ApiKeyPermission[]
  expires_in_days?: number | null
}

export interface Webhook {
  id: string
  url: string
  events: string[]
  enabled: boolean
  failure_count: number
  last_delivery_at: string | null
  last_status: number | null
  created_at: string
}

export interface WebhookWithSecret extends Webhook {
  secret: string
}

export interface WebhookCreate {
  url: string
  events: string[]
}

export type WorkspaceRole = 'owner' | 'admin' | 'editor' | 'reviewer' | 'viewer'

export interface Workspace {
  id: string
  org_id: string
  name: string
  slug: string
  role: WorkspaceRole
  created_at: string
}

export interface WorkspaceMember {
  user_id: string
  email: string
  name: string
  role: WorkspaceRole
}

export interface WorkspaceInvite {
  id: string
  email: string
  role: WorkspaceRole
  token: string
}

export interface Team {
  id: string
  workspace_id: string
  name: string
  slug: string
  description: string | null
}

export interface TeamMember {
  user_id: string
  email: string
  name: string
}

export type VersionSource = 'apply' | 'manual' | 'scheduled' | 'revert'

export interface Version {
  id: string
  workspace_id: string
  label: string
  source: VersionSource
  draft_id: string | null
  created_by_user_id: string | null
  created_at: string
}

export type ConflictType = 'both_edited' | 'main_deleted_fork_edited' | 'fork_deleted_main_edited'

export interface Conflict {
  kind: 'objects' | 'connections' | 'diagrams'
  id: string
  type: ConflictType
}

export interface ConflictReport {
  conflicts: Conflict[]
  base_version_id: string | null
  reason?: string
  main_delta?: Record<string, number>
  fork_delta?: Record<string, number>
}

export type DiagramAccessLevel = 'read' | 'write' | 'admin'

/** Exactly one of team_id / user_id is non-null. */
export interface DiagramGrant {
  team_id: string | null
  user_id: string | null
  access_level: DiagramAccessLevel
}
