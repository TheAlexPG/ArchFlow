import { renderHook, act } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useDebouncedMutation } from './use-debounced-mutation'

describe('useDebouncedMutation', () => {
  it('coalesces multiple calls within the window into one', async () => {
    const mutate = vi.fn().mockResolvedValue(null)
    const { result } = renderHook(() =>
      useDebouncedMutation({ mutate, delayMs: 50 }),
    )

    act(() => {
      result.current.queue({ name: 'P' })
      result.current.queue({ name: 'Pa' })
      result.current.queue({ name: 'Pay' })
    })

    await new Promise((r) => setTimeout(r, 80))
    expect(mutate).toHaveBeenCalledTimes(1)
    expect(mutate).toHaveBeenCalledWith({ name: 'Pay' })
  })

  it('flush() forces the pending mutation to fire immediately', async () => {
    const mutate = vi.fn().mockResolvedValue(null)
    const { result } = renderHook(() =>
      useDebouncedMutation({ mutate, delayMs: 1000 }),
    )
    act(() => {
      result.current.queue({ name: 'A' })
      result.current.flush()
    })
    await new Promise((r) => setTimeout(r, 10))
    expect(mutate).toHaveBeenCalledTimes(1)
  })
})
