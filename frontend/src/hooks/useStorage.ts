import { useContext } from "react";

import type { KeyValueStorage } from "../lib/storage";
import { StorageContext } from "../providers/storageContext";

/**
 * StorageProvider 가 끼운 저장소.
 *
 * @throws Error StorageProvider 밖에서 부르면
 */
export function useStorage(): KeyValueStorage {
  const storage = useContext(StorageContext);
  if (!storage) {
    throw new Error("useStorage 는 StorageProvider 안에서만 쓸 수 있습니다");
  }
  return storage;
}
