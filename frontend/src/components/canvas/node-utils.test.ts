import { describe, expect, it } from 'vitest'
import { C4_DIAGRAM_LEVEL_LABELS } from '../../types/model'
import { getObjectTypeLabel } from './node-utils'

describe('C4 diagram and object labels', () => {
  it('uses official L1-L4 labels and keeps landscape separate from L1 wording', () => {
    expect(C4_DIAGRAM_LEVEL_LABELS.system_landscape).toBe('Landscape')
    expect(C4_DIAGRAM_LEVEL_LABELS.system_context).toBe('L1 · System Context')
    expect(C4_DIAGRAM_LEVEL_LABELS.container).toBe('L2 · Container')
    expect(C4_DIAGRAM_LEVEL_LABELS.component).toBe('L3 · Component')
    expect(C4_DIAGRAM_LEVEL_LABELS.custom).toBe('L4 · Code')
  })

  it('labels component objects as code inside L4 code diagrams only', () => {
    expect(getObjectTypeLabel('component', 'component')).toBe('Component')
    expect(getObjectTypeLabel('component', 'custom')).toBe('Code')
  })
})
