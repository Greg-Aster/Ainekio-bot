/// <reference types="vite/client" />

// Ensure import.meta.env is available for blog-core components
// (provided by the host Astro/Vite project at runtime)
interface ImportMetaEnv {
  readonly PUBLIC_GITHUB_OWNER: string
  readonly PUBLIC_GITHUB_REPO: string
  readonly PUBLIC_GITHUB_BRANCH: string
  [key: string]: string | boolean | undefined
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
