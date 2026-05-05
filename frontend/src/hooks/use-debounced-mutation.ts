import { useCallback, useEffect, useRef } from 'react'

interface Options<T> {
  mutate: (payload: T) => Promise<unknown>
  delayMs?: number
}

export function useDebouncedMutation<T>({ mutate, delayMs = 500 }: Options<T>) {
  const pending = useRef<T | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const fire = useCallback(() => {
    if (pending.current === null) return
    const payload = pending.current
    pending.current = null
    mutate(payload)
  }, [mutate])

  const queue = useCallback(
    (payload: T) => {
      pending.current = payload
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(fire, delayMs)
    },
    [fire, delayMs],
  )

  const flush = useCallback(() => {
    if (timer.current) {
      clearTimeout(timer.current)
      timer.current = null
    }
    fire()
  }, [fire])

  // Flush on unmount so we don't lose the last edit when the user navigates away.
  useEffect(() => () => flush(), [flush])

  return { queue, flush }
}
