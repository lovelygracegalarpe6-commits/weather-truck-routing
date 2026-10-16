/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Absolute API origin when the frontend is hosted separately; empty = same origin. */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
