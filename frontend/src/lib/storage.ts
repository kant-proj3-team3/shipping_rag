// 화면이 쓰는 저장소 계약과 안전하게 읽고 쓰는 함수. 구현은 앱 루트에서 StorageProvider 로 끼운다.

import { logWarning } from "./logger";

/** 문자열 키-값 저장소. 쓸 수 없는 환경(차단 · 시크릿 창 · 용량 초과)에서는 부를 때 예외를 던진다 */
export interface KeyValueStorage {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
  removeItem: (key: string) => void;
}

/** 브라우저 localStorage 구현. 차단된 환경에서는 window.localStorage 를 읽기만 해도 예외라, 부를 때 접근한다 */
export function createBrowserStorage(): KeyValueStorage {
  return {
    getItem: (key) => localStorage.getItem(key),
    setItem: (key, value) => {
      localStorage.setItem(key, value);
    },
    removeItem: (key) => {
      localStorage.removeItem(key);
    },
  };
}

/**
 * 값을 읽는다. 읽을 수 없는 환경이면 로그를 남기고 null (값이 없는 것과 같이 다룬다)
 *
 * @param what 로그에 남길 대상 이름 (예: "테마")
 */
export function readItem(storage: KeyValueStorage, key: string, what: string): string | null {
  try {
    return storage.getItem(key);
  } catch (e) {
    logWarning(`저장소 읽기 실패: ${what}`, e);
    return null;
  }
}

/**
 * 값을 쓴다. value 가 undefined 면 지운다. 쓸 수 없는 환경이면 로그를 남기고 false (화면은 그대로 동작한다)
 *
 * @param what 로그에 남길 대상 이름 (예: "테마")
 */
export function writeItem(
  storage: KeyValueStorage,
  key: string,
  value: string | undefined,
  what: string,
): boolean {
  try {
    if (value === undefined) {
      storage.removeItem(key);
    } else {
      storage.setItem(key, value);
    }
    return true;
  } catch (e) {
    logWarning(`저장소 쓰기 실패: ${what}`, e);
    return false;
  }
}
