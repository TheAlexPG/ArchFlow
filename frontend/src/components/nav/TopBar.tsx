import { useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { useAuthStore } from '../../stores/auth-store'

export function TopBar() {
  const { logout, accessToken } = useAuthStore()
  const qc = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleExport = async () => {
    try {
      const { data } = await axios.get('/api/v1/export', {
        headers: { Authorization: `Bearer ${accessToken}` },
      })
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `archflow-export-${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      alert('Export failed')
    }
  }

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    const formData = new FormData()
    formData.append('file', file)

    try {
      const { data } = await axios.post('/api/v1/import', formData, {
        headers: { Authorization: `Bearer ${accessToken}` },
      })
      alert(`Imported ${data.created_objects} objects and ${data.created_connections} connections`)
      qc.invalidateQueries({ queryKey: ['objects'] })
      qc.invalidateQueries({ queryKey: ['connections'] })
    } catch {
      alert('Import failed — check JSON format')
    }

    e.target.value = ''
  }

  return (
    <div className="flex items-center justify-between px-4 py-2 border-b border-neutral-800 bg-neutral-900">
      <div className="flex items-center gap-3">
        <span className="font-bold text-sm">ArchFlow</span>
        <span className="text-xs text-neutral-600">|</span>
        <span className="text-xs text-neutral-400">System Landscape</span>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={handleExport}
          className="px-2 py-1 text-xs text-neutral-400 hover:text-neutral-200 bg-neutral-800 rounded border border-neutral-700 hover:border-neutral-600 transition-colors"
        >
          Export JSON
        </button>
        <button
          onClick={() => fileInputRef.current?.click()}
          className="px-2 py-1 text-xs text-neutral-400 hover:text-neutral-200 bg-neutral-800 rounded border border-neutral-700 hover:border-neutral-600 transition-colors"
        >
          Import JSON
        </button>
        <input ref={fileInputRef} type="file" accept=".json" onChange={handleImport} className="hidden" />

        <span className="text-xs text-neutral-600">|</span>

        <button
          onClick={logout}
          className="px-2 py-1 text-xs text-neutral-500 hover:text-neutral-300 transition-colors"
        >
          Sign out
        </button>
      </div>
    </div>
  )
}
