import { useMemo, useState } from 'react'
import {
  useConnections,
  useCreateFlow,
  useDeleteFlow,
  useDiagramObjects,
  useFlows,
  useObjects,
  useUpdateFlow,
} from '../../hooks/use-api'
import { useCanvasStore } from '../../stores/canvas-store'
import type { Flow, FlowStep } from '../../types/model'

interface FlowsPanelProps {
  diagramId: string
}

export function FlowsPanel({ diagramId }: FlowsPanelProps) {
  const [open, setOpen] = useState(false)
  const [editingFlow, setEditingFlow] = useState<Flow | null>(null)
  const { data: flows = [] } = useFlows(diagramId)
  const createFlow = useCreateFlow()
  const deleteFlow = useDeleteFlow()
  const { startFlow, playingFlowId } = useCanvasStore()

  const handleCreate = () => {
    const name = prompt('Flow name:')
    if (!name?.trim()) return
    createFlow.mutate(
      { diagramId, name: name.trim(), steps: [] },
      { onSuccess: (flow) => setEditingFlow(flow) },
    )
  }

  return (
    <div style={{ position: 'absolute', right: 16, top: 16, zIndex: 10 }}>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          width: 40, height: 40, borderRadius: 8,
          background: open ? '#333' : '#262626',
          border: '1px solid #404040',
          color: '#d4d4d4', cursor: 'pointer', fontSize: 16,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
        }}
        title="Flows"
      >
        ▶
      </button>

      {open && (
        <>
          <div
            style={{ position: 'fixed', inset: 0, zIndex: 9 }}
            onClick={() => {
              setOpen(false)
              setEditingFlow(null)
            }}
          />
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              position: 'absolute', right: 52, top: 0, width: 320,
              background: '#171717', border: '1px solid #333', borderRadius: 8,
              boxShadow: '0 8px 24px rgba(0,0,0,0.5)', zIndex: 10,
              display: 'flex', flexDirection: 'column', overflow: 'hidden',
              maxHeight: '70vh',
            }}
          >
            {editingFlow ? (
              <FlowEditor
                flow={editingFlow}
                diagramId={diagramId}
                onClose={() => setEditingFlow(null)}
              />
            ) : (
              <>
                <div style={{ padding: '10px 12px', borderBottom: '1px solid #262626', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div style={{ fontSize: 11, color: '#737373', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Flows
                  </div>
                  <button
                    onClick={handleCreate}
                    style={{
                      fontSize: 11, padding: '2px 8px', borderRadius: 4,
                      background: '#3b82f6', color: 'white', border: 'none', cursor: 'pointer',
                    }}
                  >
                    + New
                  </button>
                </div>
                <div style={{ overflowY: 'auto' }}>
                  {flows.length === 0 ? (
                    <div style={{ padding: 16, fontSize: 12, color: '#525252', textAlign: 'center' }}>
                      No flows yet. Create one to document user journeys.
                    </div>
                  ) : (
                    flows.map((flow) => (
                      <FlowRow
                        key={flow.id}
                        flow={flow}
                        isPlaying={flow.id === playingFlowId}
                        onPlay={() => {
                          startFlow(flow.id)
                          setOpen(false)
                        }}
                        onEdit={() => setEditingFlow(flow)}
                        onDelete={() => {
                          if (confirm(`Delete flow "${flow.name}"?`)) {
                            deleteFlow.mutate(flow.id)
                          }
                        }}
                      />
                    ))
                  )}
                </div>
              </>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function FlowRow({
  flow,
  isPlaying,
  onPlay,
  onEdit,
  onDelete,
}: {
  flow: Flow
  isPlaying: boolean
  onPlay: () => void
  onEdit: () => void
  onDelete: () => void
}) {
  const branches = useMemo(() => {
    const set = new Set<string>()
    for (const s of flow.steps) if (s.branch) set.add(s.branch)
    return [...set]
  }, [flow.steps])

  return (
    <div style={{ padding: '8px 12px', borderBottom: '1px solid #262626' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, color: '#e5e5e5', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {isPlaying && <span style={{ color: '#22c55e', marginRight: 4 }}>●</span>}
            {flow.name}
          </div>
          <div style={{ fontSize: 10, color: '#737373' }}>
            {flow.steps.length} step{flow.steps.length === 1 ? '' : 's'}
            {branches.length > 0 && ` · ${branches.length + 1} branches`}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 2 }}>
          <IconButton title="Play" onClick={onPlay}>▶</IconButton>
          <IconButton title="Edit" onClick={onEdit}>✎</IconButton>
          <IconButton title="Delete" onClick={onDelete} danger>🗑</IconButton>
        </div>
      </div>
    </div>
  )
}

function IconButton({ children, title, onClick, danger }: { children: React.ReactNode; title: string; onClick: () => void; danger?: boolean }) {
  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        width: 24, height: 24, padding: 0, fontSize: 11,
        background: 'transparent', border: 'none', borderRadius: 4,
        color: danger ? '#f87171' : '#a3a3a3',
        cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = '#262626')}
      onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
    >
      {children}
    </button>
  )
}

function FlowEditor({
  flow,
  diagramId,
  onClose,
}: {
  flow: Flow
  diagramId: string
  onClose: () => void
}) {
  const { data: allObjects = [] } = useObjects()
  const { data: diagramObjects = [] } = useDiagramObjects(diagramId)
  const { data: allConnections = [] } = useConnections()
  const updateFlow = useUpdateFlow()
  const [steps, setSteps] = useState<FlowStep[]>(flow.steps)
  const [name, setName] = useState(flow.name)

  const objectMap = useMemo(() => new Map(allObjects.map((o) => [o.id, o])), [allObjects])
  const diagramObjectIds = useMemo(
    () => new Set(diagramObjects.map((d) => d.object_id)),
    [diagramObjects],
  )
  const connections = useMemo(
    () => allConnections.filter((c) => diagramObjectIds.has(c.source_id) && diagramObjectIds.has(c.target_id)),
    [allConnections, diagramObjectIds],
  )

  const stepConnectionIds = new Set(steps.map((s) => s.connection_id))

  const handleSave = () => {
    updateFlow.mutate(
      { id: flow.id, name, steps },
      { onSuccess: onClose },
    )
  }

  const addStep = (connectionId: string, branch: string | null = null) => {
    setSteps((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        connection_id: connectionId,
        branch,
        note: null,
      },
    ])
  }

  const removeStep = (id: string) => {
    setSteps((prev) => prev.filter((s) => s.id !== id))
  }

  const moveStep = (id: string, dir: -1 | 1) => {
    setSteps((prev) => {
      const idx = prev.findIndex((s) => s.id === id)
      if (idx < 0) return prev
      const next = idx + dir
      if (next < 0 || next >= prev.length) return prev
      const copy = [...prev]
      ;[copy[idx], copy[next]] = [copy[next], copy[idx]]
      return copy
    })
  }

  const setStepBranch = (id: string, branch: string | null) => {
    setSteps((prev) => prev.map((s) => (s.id === id ? { ...s, branch } : s)))
  }

  return (
    <>
      <div style={{ padding: '10px 12px', borderBottom: '1px solid #262626', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          style={{
            flex: 1, background: 'transparent', border: 'none',
            color: '#f5f5f5', fontSize: 13, fontWeight: 600, outline: 'none',
          }}
        />
        <button
          onClick={onClose}
          style={{ background: 'transparent', border: 'none', color: '#737373', cursor: 'pointer', fontSize: 16 }}
        >
          ×
        </button>
      </div>

      <div style={{ padding: '10px 12px', flex: 1, overflowY: 'auto' }}>
        <div style={{ fontSize: 10, color: '#737373', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>
          Steps ({steps.length})
        </div>
        {steps.length === 0 ? (
          <div style={{ fontSize: 11, color: '#525252', marginBottom: 12 }}>
            No steps yet. Pick connections below to add.
          </div>
        ) : (
          <div style={{ marginBottom: 12 }}>
            {steps.map((s, idx) => {
              const conn = allConnections.find((c) => c.id === s.connection_id)
              const source = conn ? objectMap.get(conn.source_id) : null
              const target = conn ? objectMap.get(conn.target_id) : null
              return (
                <div
                  key={s.id}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 6,
                    padding: '4px 6px', fontSize: 11, color: '#d4d4d4',
                    borderLeft: '2px solid #3b82f6', marginBottom: 4,
                  }}
                >
                  <span style={{
                    width: 18, height: 18, borderRadius: '50%',
                    background: '#3b82f6', color: 'white', fontSize: 10, fontWeight: 700,
                    display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                  }}>
                    {idx + 1}
                  </span>
                  <div style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {source?.name || '?'} → {target?.name || '?'}
                  </div>
                  <input
                    value={s.branch || ''}
                    onChange={(e) => setStepBranch(s.id, e.target.value || null)}
                    placeholder="branch"
                    style={{
                      width: 60, background: '#262626', border: '1px solid #333',
                      borderRadius: 3, padding: '1px 4px', color: '#a3a3a3', fontSize: 10,
                    }}
                  />
                  <IconButton title="Up" onClick={() => moveStep(s.id, -1)}>▲</IconButton>
                  <IconButton title="Down" onClick={() => moveStep(s.id, 1)}>▼</IconButton>
                  <IconButton title="Remove" onClick={() => removeStep(s.id)} danger>×</IconButton>
                </div>
              )
            })}
          </div>
        )}

        <div style={{ fontSize: 10, color: '#737373', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>
          Connections in diagram
        </div>
        {connections.length === 0 ? (
          <div style={{ fontSize: 11, color: '#525252' }}>No connections yet.</div>
        ) : (
          connections.map((c) => {
            const source = objectMap.get(c.source_id)
            const target = objectMap.get(c.target_id)
            return (
              <button
                key={c.id}
                onClick={() => addStep(c.id)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  width: '100%', padding: '4px 6px', marginBottom: 2,
                  background: 'transparent', border: 'none', borderRadius: 4,
                  color: stepConnectionIds.has(c.id) ? '#525252' : '#d4d4d4',
                  fontSize: 11, cursor: 'pointer', textAlign: 'left',
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = '#262626')}
                onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
              >
                <span style={{ color: '#3b82f6' }}>+</span>
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {source?.name || '?'} → {target?.name || '?'}
                </span>
                {c.label && <span style={{ fontSize: 10, color: '#737373' }}>{c.label}</span>}
              </button>
            )
          })
        )}
      </div>

      <div style={{ padding: '8px 12px', borderTop: '1px solid #262626', display: 'flex', gap: 6 }}>
        <button
          onClick={handleSave}
          disabled={updateFlow.isPending}
          style={{
            flex: 1, padding: '6px', fontSize: 12, borderRadius: 4,
            background: '#3b82f6', color: 'white', border: 'none', cursor: 'pointer',
          }}
        >
          Save
        </button>
        <button
          onClick={onClose}
          style={{
            padding: '6px 12px', fontSize: 12, borderRadius: 4,
            background: 'transparent', color: '#a3a3a3', border: '1px solid #333', cursor: 'pointer',
          }}
        >
          Cancel
        </button>
      </div>
    </>
  )
}
