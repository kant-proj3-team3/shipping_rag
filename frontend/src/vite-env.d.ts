/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API 주소 (lib/config.ts 의 API_BASE). 비우면 같은 주소로 보낸다 */
  readonly VITE_API_BASE?: string;
  /** 기본 검색 방식 (lib/config.ts 의 DEFAULT_RETRIEVAL_MODE). naive · hybrid · hybrid_rerank, 비우면 hybrid_rerank */
  readonly VITE_DEFAULT_RETRIEVAL_MODE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
