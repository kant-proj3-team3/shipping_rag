import { useContext } from "react";

import type { ApiClient } from "../api/client";
import { ApiContext } from "../providers/apiContext";

/**
 * ApiProvider 가 끼운 API 클라이언트.
 *
 * @throws Error ApiProvider 밖에서 부르면
 */
export function useApi(): ApiClient {
  const client = useContext(ApiContext);
  if (!client) {
    throw new Error("useApi 는 ApiProvider 안에서만 쓸 수 있습니다");
  }
  return client;
}
