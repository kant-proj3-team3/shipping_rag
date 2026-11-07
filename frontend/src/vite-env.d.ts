/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API 주소 (lib/config.ts 의 API_BASE). 비우면 같은 주소로 보낸다 */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
