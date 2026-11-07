import { createContext } from "react";

import type { ApiClient } from "../api/client";

/** 앱이 쓰는 API 클라이언트. ApiProvider 가 채운다 */
export const ApiContext = createContext<ApiClient | undefined>(undefined);
