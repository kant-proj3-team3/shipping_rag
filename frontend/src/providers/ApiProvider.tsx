import type { ReactNode } from "react";

import { ApiContext } from "./apiContext";
import type { ApiClient } from "../api/client";

interface ApiProviderProps {
  client: ApiClient;
  children: ReactNode;
}

/** 하위 컴포넌트가 useApi() 로 꺼내 쓸 API 클라이언트를 끼운다 (실제 서버 · 테스트용 가짜) */
export function ApiProvider({ client, children }: ApiProviderProps) {
  return <ApiContext value={client}>{children}</ApiContext>;
}
