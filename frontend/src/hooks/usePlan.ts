import { useCallback, useRef, useState } from 'react'
import { api } from '../api/client'
import type { PlanRequest, PlanResponse } from '../api/types'

export type Status = 'idle' | 'loading' | 'success' | 'error'

interface PlanState {
  status: Status
  data: PlanResponse | null
  error: string | null
}

/** Runs trip plans; keeps the previous result on screen while a new one loads. */
export function usePlan() {
  const [state, setState] = useState<PlanState>({ status: 'idle', data: null, error: null })
  const controller = useRef<AbortController | null>(null)

  const run = useCallback(async (request: PlanRequest) => {
    controller.current?.abort()
    const ctrl = new AbortController()
    controller.current = ctrl
    setState((s) => ({ ...s, status: 'loading', error: null }))
    try {
      const data = await api.plan(request, ctrl.signal)
      setState({ status: 'success', data, error: null })
    } catch (error) {
      if ((error as Error).name === 'AbortError') return
      setState((s) => ({ ...s, status: 'error', error: (error as Error).message }))
    }
  }, [])

  const fail = useCallback((message: string) => {
    setState((s) => ({ ...s, status: 'error', error: message }))
  }, [])

  return { ...state, run, fail }
}
