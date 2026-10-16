import { memo } from 'react'
import type { IntervalMiles } from '../api/types'
import { Icon } from './Icon'
import { PlaceInput, type PlaceValue } from './PlaceInput'

export interface TripFormState {
  origin: PlaceValue
  destination: PlaceValue
  /** datetime-local value (origin wall time) or '' for "leave now" */
  departure: string
  loadWeight: string
  interval: IntervalMiles
}

interface Props {
  value: TripFormState
  onChange: (value: TripFormState) => void
  onSubmit: () => void
  busy: boolean
}

const INTERVALS: IntervalMiles[] = [10, 25, 50]
const LOAD_PRESETS = [20_000, 35_000, 45_000]

export const TripForm = memo(function TripForm({ value, onChange, onSubmit, busy }: Props) {
  const set = <K extends keyof TripFormState>(key: K, v: TripFormState[K]) => onChange({ ...value, [key]: v })

  return (
    <form
      className="trip-form"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit()
      }}
    >
      <div className="places" role="group" aria-label="Trip">
        <PlaceInput
          label="Origin"
          marker="origin"
          placeholder="Origin — city or address"
          value={value.origin}
          onChange={(v) => set('origin', v)}
        />
        <button
          type="button"
          className="swap"
          title="Swap origin and destination"
          aria-label="Swap origin and destination"
          onClick={() => onChange({ ...value, origin: value.destination, destination: value.origin })}
        >
          <Icon name="swap" size={15} />
        </button>
        <PlaceInput
          label="Destination"
          marker="destination"
          placeholder="Destination — city or address"
          value={value.destination}
          onChange={(v) => set('destination', v)}
        />
      </div>

      <div className="form-grid">
      <div className="field">
        <label htmlFor="departure">Departure</label>
        <div className="inline">
          <input
            id="departure"
            type="datetime-local"
            value={value.departure}
            onChange={(e) => set('departure', e.target.value)}
          />
          {value.departure && (
            <button type="button" className="link" onClick={() => set('departure', '')}>
              Leave now
            </button>
          )}
        </div>
        <p className="hint">{value.departure ? 'Local time at the origin.' : 'Blank = leave now.'}</p>
      </div>

      <div className="field">
        <label htmlFor="load">Load weight</label>
        <div className="with-unit">
          <input
            id="load"
            type="number"
            inputMode="numeric"
            min={0}
            max={200000}
            step={500}
            required
            value={value.loadWeight}
            onChange={(e) => set('loadWeight', e.target.value)}
          />
          <span>lb</span>
        </div>
        <div className="chips" role="group" aria-label="Load presets">
          {LOAD_PRESETS.map((lb) => (
            <button
              key={lb}
              type="button"
              className={Number(value.loadWeight) === lb ? 'chip on' : 'chip'}
              onClick={() => set('loadWeight', String(lb))}
            >
              {lb / 1000}k
            </button>
          ))}
        </div>
      </div>
      </div>
      <p className="hint">Wind risk rises for loads over 30,000 lb and 40,000 lb.</p>

      <div className="field">
        <span className="label" id="interval-label">
          Weather checkpoint every
        </span>
        <div className="segmented" role="radiogroup" aria-labelledby="interval-label">
          {INTERVALS.map((mi) => (
            <button
              key={mi}
              type="button"
              role="radio"
              aria-checked={value.interval === mi}
              className={value.interval === mi ? 'on' : undefined}
              onClick={() => set('interval', mi)}
            >
              {mi} mi
            </button>
          ))}
        </div>
      </div>

      <button type="submit" className="primary" disabled={busy}>
        {busy ? (
          <>
            <span className="spinner" aria-hidden="true" /> Checking routes &amp; weather…
          </>
        ) : (
          <>
            <Icon name="spark" size={17} /> Find the safest route
          </>
        )}
      </button>
    </form>
  )
})
