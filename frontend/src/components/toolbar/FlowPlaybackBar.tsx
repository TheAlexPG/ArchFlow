import { useEffect, useMemo } from 'react'
import { useFlows } from '../../hooks/use-api'
import { useCanvasStore } from '../../stores/canvas-store'

interface FlowPlaybackBarProps {
  diagramId: string
}

export function FlowPlaybackBar({ diagramId }: FlowPlaybackBarProps) {
  const { data: flows = [] } = useFlows(diagramId)
  const {
    playingFlowId,
    playingStepIdx,
    activeBranch,
    stopFlow,
    setFlowStep,
    setFlowBranch,
  } = useCanvasStore()

  const flow = flows.find((f) => f.id === playingFlowId)

  // Branches available in this flow. "main" is the implicit default for
  // steps with branch === null.
  const branches = useMemo(() => {
    if (!flow) return []
    const set = new Set<string>()
    set.add('main')
    for (const s of flow.steps) if (s.branch) set.add(s.branch)
    return [...set]
  }, [flow])

  const stepsForBranch = useMemo(() => {
    if (!flow) return []
    if (!activeBranch || activeBranch === 'main') {
      return flow.steps.filter((s) => !s.branch)
    }
    return flow.steps.filter((s) => s.branch === activeBranch)
  }, [flow, activeBranch])

  // Clamp index if the branch changed and we're past the new end.
  useEffect(() => {
    if (playingStepIdx >= stepsForBranch.length && stepsForBranch.length > 0) {
      setFlowStep(stepsForBranch.length - 1)
    }
  }, [stepsForBranch.length, playingStepIdx, setFlowStep])

  // ESC stops playback.
  useEffect(() => {
    if (!playingFlowId) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') stopFlow()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [playingFlowId, stopFlow])

  if (!flow) return null

  const canPrev = playingStepIdx > 0
  const canNext = playingStepIdx < stepsForBranch.length - 1

  return (
    <div
      style={{
        position: 'absolute',
        bottom: 70,
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 20,
        background: '#171717',
        border: '1px solid #3b82f6',
        borderRadius: 10,
        padding: '10px 14px',
        color: '#e5e5e5',
        fontSize: 12,
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
        minWidth: 360,
      }}
    >
      <span style={{ color: '#60a5fa' }}>▶</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {flow.name}
        </div>
        <div style={{ fontSize: 10, color: '#737373' }}>
          Step {Math.min(playingStepIdx + 1, stepsForBranch.length)} / {stepsForBranch.length}
          {stepsForBranch.length === 0 && ' · no steps in this branch'}
        </div>
      </div>

      {branches.length > 1 && (
        <select
          value={activeBranch || 'main'}
          onChange={(e) => setFlowBranch(e.target.value === 'main' ? null : e.target.value)}
          style={{
            background: '#262626', border: '1px solid #333', borderRadius: 4,
            color: '#e5e5e5', fontSize: 11, padding: '3px 6px',
          }}
        >
          {branches.map((b) => (
            <option key={b} value={b}>
              {b}
            </option>
          ))}
        </select>
      )}

      <button
        onClick={() => setFlowStep(Math.max(0, playingStepIdx - 1))}
        disabled={!canPrev}
        style={{
          padding: '4px 8px', fontSize: 12, borderRadius: 4,
          background: 'transparent', color: canPrev ? '#a3a3a3' : '#525252',
          border: '1px solid #333', cursor: canPrev ? 'pointer' : 'not-allowed',
        }}
      >
        ◀ Prev
      </button>
      <button
        onClick={() => setFlowStep(playingStepIdx + 1)}
        disabled={!canNext}
        style={{
          padding: '4px 8px', fontSize: 12, borderRadius: 4,
          background: canNext ? '#3b82f6' : 'transparent',
          color: canNext ? 'white' : '#525252',
          border: `1px solid ${canNext ? '#3b82f6' : '#333'}`,
          cursor: canNext ? 'pointer' : 'not-allowed',
        }}
      >
        Next ▶
      </button>
      <button
        onClick={stopFlow}
        style={{
          padding: '4px 8px', fontSize: 12, borderRadius: 4,
          background: 'transparent', color: '#f87171', border: '1px solid #7f1d1d',
          cursor: 'pointer',
        }}
      >
        Stop
      </button>
    </div>
  )
}
