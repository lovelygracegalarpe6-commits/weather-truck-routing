import { useEffect, useId, useState } from 'react'
import { api } from '../api/client'
import type { Place } from '../api/types'

export interface PlaceValue {
  text: string
  place: Place | null
}

interface Props {
  label: string
  value: PlaceValue
  onChange: (value: PlaceValue) => void
  placeholder?: string
  marker: 'origin' | 'destination'
}

const DEBOUNCE_MS = 250

export function PlaceInput({ label, value, onChange, placeholder, marker }: Props) {
  const id = useId()
  const [suggestions, setSuggestions] = useState<Place[]>([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const [loading, setLoading] = useState(false)

  const query = value.place ? '' : value.text.trim()

  useEffect(() => {
    if (query.length < 3) return
    const ctrl = new AbortController()
    const timer = setTimeout(() => {
      setLoading(true)
      api
        .geocode(query, ctrl.signal)
        .then(({ results }) => {
          setSuggestions(results)
          setActive(results.length ? 0 : -1)
          setOpen(true)
        })
        .catch(() => setSuggestions([]))
        .finally(() => setLoading(false))
    }, DEBOUNCE_MS)
    return () => {
      clearTimeout(timer)
      ctrl.abort()
    }
  }, [query])

  const choose = (place: Place) => {
    onChange({ text: place.label, place })
    setOpen(false)
    setSuggestions([])
  }

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open || suggestions.length === 0) return
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActive((a) => (a + 1) % suggestions.length)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((a) => (a - 1 + suggestions.length) % suggestions.length)
    } else if (event.key === 'Enter' && active >= 0) {
      event.preventDefault()
      choose(suggestions[active])
    } else if (event.key === 'Escape') {
      setOpen(false)
    }
  }

  const listId = `${id}-list`
  const showList = open && query.length >= 3 && suggestions.length > 0

  return (
    <div className="field place-field">
      <label htmlFor={id}>{label}</label>
      <div className={`place-input ${marker}`}>
        <span className="place-dot" aria-hidden="true" />
        <input
          id={id}
          type="text"
          autoComplete="off"
          spellCheck={false}
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={showList && active >= 0 ? `${listId}-${active}` : undefined}
          placeholder={placeholder}
          value={value.text}
          onChange={(e) => {
            onChange({ text: e.target.value, place: null })
            setOpen(true)
          }}
          onKeyDown={onKeyDown}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
        />
        {loading && <span className="spinner small" aria-label="Searching" />}
        {value.place && <span className="check" title="Location confirmed" aria-hidden="true">✓</span>}
      </div>
      {showList && (
        <ul id={listId} role="listbox" className="suggestions">
          {suggestions.map((place, i) => (
            <li
              id={`${listId}-${i}`}
              key={`${place.label}-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? 'active' : undefined}
              onMouseDown={(e) => {
                e.preventDefault() // keep focus so blur doesn't close before the click lands
                choose(place)
              }}
              onMouseEnter={() => setActive(i)}
            >
              {place.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
