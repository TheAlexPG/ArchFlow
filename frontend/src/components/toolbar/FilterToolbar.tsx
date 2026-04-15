import { useMemo, useState } from 'react'
import { useObjects } from '../../hooks/use-api'
import { STATUS_COLORS } from '../canvas/node-utils'
import type { ObjectStatus } from '../../types/model'

type FilterTab = 'tags' | 'technology' | 'status' | 'teams'

export function FilterToolbar() {
  const { data: objects = [] } = useObjects()
  const [activeTab, setActiveTab] = useState<FilterTab | null>(null)

  const stats = useMemo(() => {
    const tags = new Map<string, number>()
    const tech = new Map<string, number>()
    const status = new Map<string, number>()
    const teams = new Map<string, number>()

    for (const obj of objects) {
      obj.tags?.forEach((t) => tags.set(t, (tags.get(t) || 0) + 1))
      obj.technology?.forEach((t) => tech.set(t, (tech.get(t) || 0) + 1))
      status.set(obj.status, (status.get(obj.status) || 0) + 1)
      if (obj.owner_team) teams.set(obj.owner_team, (teams.get(obj.owner_team) || 0) + 1)
    }

    return { tags, tech, status, teams }
  }, [objects])

  const tabs: { id: FilterTab; icon: string; label: string }[] = [
    { id: 'tags', icon: '🏷', label: 'Tags' },
    { id: 'technology', icon: '⟨/⟩', label: 'Technology' },
    { id: 'status', icon: '✦', label: 'Status' },
    { id: 'teams', icon: '👥', label: 'Teams' },
  ]

  return (
    <div style={{
      position: 'absolute', bottom: 12, left: '50%', transform: 'translateX(-50%)',
      zIndex: 10, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6,
    }}>
      {/* Chips */}
      {activeTab && (
        <div style={{
          background: '#171717', border: '1px solid #333', borderRadius: 8,
          padding: '6px 10px', display: 'flex', gap: 6, flexWrap: 'wrap', maxWidth: 500,
        }}>
          {activeTab === 'status' &&
            Array.from(stats.status.entries()).map(([status, count]) => (
              <Chip
                key={status}
                label={`${status} ${count}`}
                color={STATUS_COLORS[status as ObjectStatus]}
              />
            ))}
          {activeTab === 'technology' &&
            Array.from(stats.tech.entries()).map(([t, count]) => (
              <Chip key={t} label={`${t} ${count}`} />
            ))}
          {activeTab === 'tags' &&
            Array.from(stats.tags.entries()).map(([t, count]) => (
              <Chip key={t} label={`${t} ${count}`} />
            ))}
          {activeTab === 'teams' &&
            Array.from(stats.teams.entries()).map(([t, count]) => (
              <Chip key={t} label={`${t} ${count}`} />
            ))}
          {activeTab && getMap(activeTab, stats).size === 0 && (
            <span style={{ fontSize: 11, color: '#525252' }}>No data</span>
          )}
        </div>
      )}

      {/* Tab bar */}
      <div style={{
        background: '#171717', border: '1px solid #333', borderRadius: 8,
        padding: '4px 6px', display: 'flex', gap: 2,
      }}>
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(activeTab === tab.id ? null : tab.id)}
            style={{
              background: activeTab === tab.id ? '#262626' : 'transparent',
              border: 'none', borderRadius: 6, padding: '4px 10px',
              color: activeTab === tab.id ? '#f5f5f5' : '#737373',
              cursor: 'pointer', fontSize: 12, display: 'flex', alignItems: 'center', gap: 4,
            }}
          >
            <span>{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </div>
    </div>
  )
}

function Chip({ label, color }: { label: string; color?: string }) {
  return (
    <span style={{
      fontSize: 11, padding: '2px 8px', borderRadius: 12,
      background: color ? `${color}22` : '#262626',
      color: color || '#a3a3a3',
      border: `1px solid ${color ? `${color}44` : '#333'}`,
    }}>
      {label}
    </span>
  )
}

function getMap(tab: FilterTab, stats: { tags: Map<string, number>; tech: Map<string, number>; status: Map<string, number>; teams: Map<string, number> }) {
  switch (tab) {
    case 'tags': return stats.tags
    case 'technology': return stats.tech
    case 'status': return stats.status
    case 'teams': return stats.teams
  }
}
