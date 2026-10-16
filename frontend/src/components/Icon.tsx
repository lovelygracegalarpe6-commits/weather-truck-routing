// A few stroke icons drawn for this app (24x24 grid), so no icon library is needed.
const PATHS = {
  clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2',
  route: 'M6 21a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 7a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM6 17V9a4 4 0 0 1 4-4h6M18 7v8a4 4 0 0 1-4 4H8',
  flag: 'M5 21V4M5 4h11l-2 4 2 4H5',
  alert: 'M12 3 2 20h20L12 3zM12 10v4M12 17h.01',
  check: 'M5 12.5 10 17.5 19.5 7',
  swap: 'M7 4v16M4 7l3-3 3 3M17 20V4M14 17l3 3 3-3',
  shield: 'M12 3l8 3v6c0 4.6-3.4 8-8 9-4.6-1-8-4.4-8-9V6l8-3zM8.5 12l2.5 2.5 4.5-4.5',
  cloud: 'M7 18h10a4 4 0 0 0 .5-7.97A6 6 0 0 0 6.1 11.5 3.3 3.3 0 0 0 7 18z',
  weight: 'M6.5 8h11l2.5 12H4L6.5 8zM9 8a3 3 0 0 1 6 0',
  calendar: 'M4 6h16v15H4zM4 10h16M8 3v4M16 3v4',
  layers: 'M12 3 2 8l10 5 10-5-10-5zM2 13l10 5 10-5',
  spark: 'M12 3l1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4z',
} as const

const FILLED = {
  play: 'M8 5.5v13l10.5-6.5z',
  pause: 'M7 5h3.5v14H7zM13.5 5H17v14h-3.5z',
} as const

export type IconName = keyof typeof PATHS | keyof typeof FILLED

export function Icon({ name, size = 16, className }: { name: IconName; size?: number; className?: string }) {
  const filled = name in FILLED
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
      fill={filled ? 'currentColor' : 'none'}
      stroke={filled ? 'none' : 'currentColor'}
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={filled ? FILLED[name as keyof typeof FILLED] : PATHS[name as keyof typeof PATHS]} />
    </svg>
  )
}
