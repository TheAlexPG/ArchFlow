import { useState } from 'react'
import { useCreateObject } from '../../hooks/use-api'
import type { ObjectType } from '../../types/model'
import { TYPE_ICONS, TYPE_LABELS } from '../canvas/node-utils'

const OBJECT_TYPES: ObjectType[] = ['system', 'actor', 'external_system', 'app', 'store', 'component', 'group']

export function AddObjectToolbar() {
  const [isOpen, setIsOpen] = useState(false)
  const createObject = useCreateObject()

  const handleAdd = (type: ObjectType) => {
    const name = prompt(`New ${TYPE_LABELS[type]} name:`)
    if (!name?.trim()) return
    createObject.mutate({ name: name.trim(), type })
    setIsOpen(false)
  }

  return (
    <div className="absolute left-4 top-1/2 -translate-y-1/2 z-10 flex flex-col gap-2">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-10 h-10 rounded-lg bg-neutral-800 border border-neutral-700 text-neutral-300 hover:bg-neutral-700 flex items-center justify-center text-xl shadow-lg transition-colors"
        title="Add object"
      >
        +
      </button>

      {isOpen && (
        <div className="bg-neutral-800 border border-neutral-700 rounded-lg shadow-xl p-2 min-w-[180px]">
          <div className="text-xs text-neutral-500 px-2 py-1 uppercase tracking-wider">Add object</div>
          {OBJECT_TYPES.map((type) => (
            <button
              key={type}
              onClick={() => handleAdd(type)}
              className="w-full text-left px-2 py-1.5 rounded text-sm text-neutral-300 hover:bg-neutral-700 flex items-center gap-2 transition-colors"
            >
              <span className="w-5 text-center opacity-60">{TYPE_ICONS[type]}</span>
              {TYPE_LABELS[type]}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
