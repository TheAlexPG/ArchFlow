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

export interface DraftItem {
  id: string
  draft_id: string
  target_type: string
  target_id: string | null
  baseline: Record<string, unknown> | null
  proposed_state: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface Draft {
  id: string
  name: string
  description: string | null
  status: DraftStatus
  author_id: string | null
  items: DraftItem[]
  created_at: string
  updated_at: string
}

export interface DraftCreate {
  name: string
  description?: string | null
}

export interface DraftItemCreate {
  target_type?: string
  target_id?: string | null
  proposed_state: Record<string, unknown>
}
