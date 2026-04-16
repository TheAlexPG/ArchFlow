import { useMemo } from 'react'
import { useObjects } from '../../hooks/use-api'
import { useCanvasStore } from '../../stores/canvas-store'
import { collectLegend, type FilterDim } from '../canvas/overlay-utils'

const TABS: { id: Exclude<FilterDim, 'none'>; icon: string; label: string }[] = [
  { id: 'tags', icon: '🏷', label: 'Tags' },
  { id: 'technology', icon: '⟨/⟩', label: 'Technology' },
  { id: 'status', icon: '✦', label: 'Status' },
  { id: 'teams', icon: '👥', label: 'Teams' },
]

export function FilterToolbar() {
  const { data: objects = [] } = useObjects()
  const {
    activeFilter,
    activeFilterValue,
    setActiveFilter,
    setActiveFilterValue,
  } = useCanvasStore()

  const legend = useMemo(
    () => collectLegend(objects, activeFilter as FilterDim),
    [objects, activeFilter],
  )

  return (
    <div style={{
      position: 'absolute', bottom: 12, left: '50%', transform: 'translateX(-50%)',
      zIndex: 10, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6,
    }}>
      {/* Legend — values with their color swatches for the active dimension */}
      {activeFilter !== 'none' && (
        <div style={{
          background: '#171717', border: '1px solid #333', borderRadius: 8,
          padding: '6px 10px', display: 'flex', gap: 6, flexWrap: 'wrap', maxWidth: 560,
        }}>
          {legend.length === 0 ? (
            <span style={{ fontSize: 11, color: '#525252' }}>
              No data for this dimension
            </span>
          ) : (
            legend.map(({ value, color, count }) => (
              <Chip
                key={value}
                label={value}
                count={count}
                color={color}
                active={activeFilterValue === value}
                dimmed={!!activeFilterValue && activeFilterValue !== value}
                onClick={() =>
                  setActiveFilterValue(activeFilterValue === value ? null : value)
                }
              />
            ))
          )}
        </div>
      )}

      {/* Tab bar */}
      <div style={{
        background: '#171717', border: '1px solid #333', borderRadius: 8,
        padding: '4px 6px', display: 'flex', gap: 2,
      }}>
        {TABS.map((tab) => {
          const active = activeFilter === tab.id
          return (
            <button
              key={tab.id}
              onClick={() => setActiveFilter(active ? 'none' : tab.id)}
              style={{
                background: active ? '#262626' : 'transparent',
                border: 'none', borderRadius: 6, padding: '4px 10px',
                color: active ? '#f5f5f5' : '#737373',
                cursor: 'pointer', fontSize: 12, display: 'flex', alignItems: 'center', gap: 4,
              }}
            >
              <span>{tab.icon}</span>
              {tab.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}

function Chip({
  label,
  count,
  color,
  active,
  dimmed,
  onClick,
}: {
  label: string
  count: number
  color: string
  active?: boolean
  dimmed?: boolean
  onClick?: () => void
}) {
  return (
    <button
      onClick={onClick}
      style={{
        fontSize: 11, padding: '2px 8px', borderRadius: 12,
        background: active ? color : `${color}22`,
        color: active ? '#0a0a0a' : color,
        border: `1px solid ${active ? color : `${color}66`}`,
        display: 'inline-flex', alignItems: 'center', gap: 6,
        cursor: onClick ? 'pointer' : 'default',
        opacity: dimmed ? 0.4 : 1,
        fontWeight: active ? 600 : 400,
      }}
    >
      {label}
      <span
        style={{
          color: active ? '#0a0a0a' : '#737373',
          fontSize: 10,
          opacity: active ? 0.7 : 1,
        }}
      >
        {count}
      </span>
    </button>
  )
}
