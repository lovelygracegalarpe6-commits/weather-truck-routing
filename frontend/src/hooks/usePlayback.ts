import { useEffect, useRef } from 'react'

/** Advances `hours` smoothly with requestAnimationFrame while playing, looping at the end. */
export function usePlayback(
  playing: boolean,
  setHours: (update: (h: number) => number) => void,
  maxHours: number,
  hoursPerSecond = 2,
) {
  const last = useRef<number | null>(null)

  useEffect(() => {
    if (!playing) return
    let frame = 0
    const tick = (now: number) => {
      const dt = last.current === null ? 0 : (now - last.current) / 1000
      last.current = now
      setHours((h) => {
        const next = h + dt * hoursPerSecond
        return next > maxHours ? 0 : next
      })
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(frame)
      last.current = null
    }
  }, [playing, setHours, maxHours, hoursPerSecond])
}
