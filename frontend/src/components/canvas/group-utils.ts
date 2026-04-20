import type { DiagramObjectData } from '../../hooks/use-api'
import type { ModelObject } from '../../types/model'

interface Rect {
  x: number
  y: number
  width: number
  height: number
}

/** Default sizes used when width/height are null in the diagram row. */
const DEFAULT_REGULAR_W = 160
const DEFAULT_REGULAR_H = 60
const DEFAULT_GROUP_W = 300
const DEFAULT_GROUP_H = 200

function isFullyContained(inner: Rect, outer: Rect): boolean {
  return (
    inner.x >= outer.x &&
    inner.y >= outer.y &&
    inner.x + inner.width <= outer.x + outer.width &&
    inner.y + inner.height <= outer.y + outer.height
  )
}

function placementRect(
  dObj: DiagramObjectData,
  obj: ModelObject,
): Rect {
  const isGroup = obj.type === 'group'
  return {
    x: dObj.position_x,
    y: dObj.position_y,
    width: dObj.width ?? (isGroup ? DEFAULT_GROUP_W : DEFAULT_REGULAR_W),
    height: dObj.height ?? (isGroup ? DEFAULT_GROUP_H : DEFAULT_REGULAR_H),
  }
}

/**
 * Given the bounding rect of a dropped/dragged node, find the deepest
 * group-type object on the same diagram whose rectangle fully contains it.
 *
 * Returns the group's object_id, or null if no group contains the node.
 *
 * Rules:
 * - Only looks at objects whose ModelObject.type === 'group'.
 * - Excludes the node being moved itself (droppedNodeId).
 * - When multiple groups contain the node, picks the one with the smallest
 *   area (deepest / most specific ancestor).
 */
export function detectParentGroup(
  droppedNodeId: string,
  nodeRect: Rect,
  allPlacements: DiagramObjectData[],
  allObjects: ModelObject[],
): string | null {
  const objectMap = new Map(allObjects.map((o) => [o.id, o]))

  let bestGroupId: string | null = null
  let bestArea = Infinity

  for (const dObj of allPlacements) {
    if (dObj.object_id === droppedNodeId) continue
    const obj = objectMap.get(dObj.object_id)
    if (!obj || obj.type !== 'group') continue

    const groupRect = placementRect(dObj, obj)
    if (isFullyContained(nodeRect, groupRect)) {
      const area = groupRect.width * groupRect.height
      if (area < bestArea) {
        bestArea = area
        bestGroupId = dObj.object_id
      }
    }
  }

  return bestGroupId
}

/**
 * Find every diagram object whose rectangle is fully contained within the
 * given group's rectangle on the same diagram. Purely spatial — ignores
 * parent_id. Used while dragging a group so nodes that happen to sit
 * inside follow along, even if parent_id was never persisted.
 */
export function findSpatialGroupMembers(
  groupId: string,
  allPlacements: DiagramObjectData[],
  allObjects: ModelObject[],
): string[] {
  const objectMap = new Map(allObjects.map((o) => [o.id, o]))
  const groupPlacement = allPlacements.find((p) => p.object_id === groupId)
  const groupObj = objectMap.get(groupId)
  if (!groupPlacement || !groupObj || groupObj.type !== 'group') return []

  const groupRect = placementRect(groupPlacement, groupObj)
  const members: string[] = []
  for (const dObj of allPlacements) {
    if (dObj.object_id === groupId) continue
    const obj = objectMap.get(dObj.object_id)
    if (!obj) continue
    const childRect = placementRect(dObj, obj)
    if (isFullyContained(childRect, groupRect)) {
      members.push(dObj.object_id)
    }
  }
  return members
}

/**
 * Build a rect from a ReactFlow node's current position and rendered size,
 * falling back to defaults if the node hasn't been measured yet.
 */
export function nodeToRect(
  nodeId: string,
  position: { x: number; y: number },
  width: number | undefined,
  height: number | undefined,
  allObjects: ModelObject[],
): Rect {
  const obj = allObjects.find((o) => o.id === nodeId)
  const isGroup = obj?.type === 'group'
  return {
    x: position.x,
    y: position.y,
    width: width ?? (isGroup ? DEFAULT_GROUP_W : DEFAULT_REGULAR_W),
    height: height ?? (isGroup ? DEFAULT_GROUP_H : DEFAULT_REGULAR_H),
  }
}
