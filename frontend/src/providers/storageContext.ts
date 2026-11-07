import { createContext } from "react";

import type { KeyValueStorage } from "../lib/storage";

/** 앱이 쓰는 저장소. StorageProvider 가 채운다 */
export const StorageContext = createContext<KeyValueStorage | undefined>(undefined);
