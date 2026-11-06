import type { ReactNode } from "react";

import { StorageContext } from "./storageContext";
import type { KeyValueStorage } from "../lib/storage";

interface StorageProviderProps {
  storage: KeyValueStorage;
  children: ReactNode;
}

/** 하위 컴포넌트가 useStorage() 로 꺼내 쓸 저장소를 끼운다 (브라우저 localStorage · 테스트용 가짜) */
export function StorageProvider({ storage, children }: StorageProviderProps) {
  return <StorageContext value={storage}>{children}</StorageContext>;
}
