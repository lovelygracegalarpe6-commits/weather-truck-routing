export function formatDuration(seconds: number): string {
  const minutes = Math.round(seconds / 60)
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (h === 0) return `${m}m`
  return `${h}h ${String(m).padStart(2, '0')}m`
}

export function formatMiles(miles: number): string {
  if (miles === 0) return '0 mi'
  if (miles < 10) return `${miles.toFixed(1)} mi`
  return `${Math.round(miles).toLocaleString('en-US')} mi`
}

export function formatPounds(lb: number): string {
  return `${Math.round(lb).toLocaleString('en-US')} lb`
}

const formatters = new Map<string, Intl.DateTimeFormat>()

function formatter(timeZone: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = timeZone + JSON.stringify(options)
  let f = formatters.get(key)
  if (!f) {
    f = new Intl.DateTimeFormat('en-US', { timeZone, ...options })
    formatters.set(key, f)
  }
  return f
}

/** "Sat 3:05 PM CDT" in the given IANA zone. */
export function formatDateTime(value: string | number | Date, timeZone: string): string {
  return formatter(timeZone, {
    weekday: 'short',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  }).format(new Date(value))
}

/** "Oct 17, 3:05 PM" in the given IANA zone. */
export function formatDateTimeLong(value: string | number | Date, timeZone: string): string {
  return formatter(timeZone, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  }).format(new Date(value))
}

export function formatHoursOffset(hours: number): string {
  const whole = Math.floor(hours)
  const minutes = Math.round((hours - whole) * 60)
  if (minutes === 0) return `+${whole}h`
  return `+${whole}h ${String(minutes).padStart(2, '0')}m`
}

export function formatNumber(value: number, digits: number): string {
  return value.toFixed(digits)
}
