import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ReactNode } from 'react'
import type { Connection } from '../types/model'
import {
  clearConnectionDeleted,
  clearDiagramObjectRemoved,
  markConnectionDeleted,
} from './use-realtime'

const h = vi.hoisted(() => ({
  api: {
    post: vi.fn(),
    delete: vi.fn(),
    put: vi.fn(),
    get: vi.fn(),
  },
}))

vi.mock('../lib/api-client', () => ({
  api: h.api,
}))

import {
  type DiagramObjectData,
  useAddObjectToDiagram,
  useRemoveObjectFromDiagram,
  useUpdateConnection,
} from './use-api'

function wrapperFor(qc: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  }
}

describe('canvas add/remove race cache handling', () => {
  let qc: QueryClient

  beforeEach(() => {
    qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    h.api.post.mockReset()
    h.api.delete.mockReset()
    h.api.put.mockReset()
    h.api.get.mockReset()
    clearDiagramObjectRemoved('d1', 'o1')
    clearConnectionDeleted('c1')
  })

  it('optimistically inserts a diagram placement and replaces it with the committed row', async () => {
    qc.setQueryData<DiagramObjectData[]>(['diagram-objects', 'd1'], [])
    let resolvePost!: (value: { data: DiagramObjectData }) => void
    h.api.post.mockReturnValue(new Promise((resolve) => { resolvePost = resolve }))

    const { result } = renderHook(() => useAddObjectToDiagram(), { wrapper: wrapperFor(qc) })

    act(() => {
      result.current.mutate({ diagramId: 'd1', objectId: 'o1', x: 10, y: 20 })
    })

    await waitFor(() => {
      expect(qc.getQueryData<DiagramObjectData[]>(['diagram-objects', 'd1'])).toMatchObject([
        { diagram_id: 'd1', object_id: 'o1', position_x: 10, position_y: 20 },
      ])
    })

    act(() => {
      resolvePost({ data: { id: 'server-row', diagram_id: 'd1', object_id: 'o1', position_x: 10, position_y: 20, width: null, height: null } })
    })

    await waitFor(() => {
      expect(qc.getQueryData<DiagramObjectData[]>(['diagram-objects', 'd1'])).toEqual([
        { id: 'server-row', diagram_id: 'd1', object_id: 'o1', position_x: 10, position_y: 20, width: null, height: null },
      ])
    })
  })

  it('rolls back optimistic placement removal when delete fails', async () => {
    const existing = { id: 'row-1', diagram_id: 'd1', object_id: 'o1', position_x: 0, position_y: 0, width: null, height: null }
    qc.setQueryData<DiagramObjectData[]>(['diagram-objects', 'd1'], [existing])
    h.api.delete.mockRejectedValue(new Error('nope'))

    const { result } = renderHook(() => useRemoveObjectFromDiagram(), { wrapper: wrapperFor(qc) })

    await act(async () => {
      await result.current.mutateAsync({ diagramId: 'd1', objectId: 'o1' }).catch(() => undefined)
    })

    expect(qc.getQueryData<DiagramObjectData[]>(['diagram-objects', 'd1'])).toEqual([existing])
  })

  it('does not apply a stale connection update after the connection was deleted', async () => {
    const updated: Connection = {
      id: 'c1',
      source_id: 'a',
      target_id: 'b',
      label: 'stale',
      protocol_ids: null,
      direction: 'unidirectional',
      tags: null,
      source_handle: null,
      target_handle: null,
      shape: 'smoothstep',
      label_size: 11,
      via_object_ids: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    qc.setQueryData<Connection[]>(['connections', { draftId: null }], [])
    markConnectionDeleted('c1')
    h.api.put.mockResolvedValue({ data: updated })

    const { result } = renderHook(() => useUpdateConnection(), { wrapper: wrapperFor(qc) })

    await act(async () => {
      await result.current.mutateAsync({ id: 'c1', label: 'stale' })
    })

    expect(qc.getQueryData<Connection[]>(['connections', { draftId: null }])).toEqual([])
    expect(qc.getQueryData<Connection>(['connections', 'c1'])).toBeUndefined()
  })
})
