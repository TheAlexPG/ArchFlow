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
  created_at: string
  updated_at: string
}

export interface Diagram {
  id: string
  name: string
  type: DiagramType
  description: string | null
  scope_object_id: string | null
  settings: Record<string, unknown> | null
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
}
