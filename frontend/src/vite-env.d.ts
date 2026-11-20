/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  /** Person responsible in the privacy policy; set only in the untracked `.env.production.local`. */
  readonly VITE_PRIVACY_OWNER_NAME?: string;
  /** Their address, from the same file. */
  readonly VITE_PRIVACY_OWNER_ADDRESS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
