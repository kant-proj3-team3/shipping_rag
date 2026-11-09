// 브라우저 스택의 빌드 파일 위치를 원본 소스 위치로 바꾼다. 소스맵은 이 서버에만 있고 공개하지 않는다.

import { readdirSync, readFileSync } from "node:fs";
import { SourceMap, type SourceMapPayload } from "node:module";
import path from "node:path";

import type { LogSink } from "./logger.ts";

// http://host/assets/index-abc123.js:1:2345 꼴. 스택은 브라우저가 보낸 값이라 파일 이름은 읽어 둔 소스맵에서만 찾는다
const FRAME_LOCATION = /(?:[a-z]+:\/\/[^\s()/]+)?\/assets\/([\w.-]+\.js):(\d+):(\d+)/g;
const APP_SOURCE_PREFIX = "src/";

interface MappedStack {
  stack: string;
  /** 앱 코드의 첫 위치(src/App.tsx:12). 앱 코드가 없으면 첫 위치, 바꾼 곳이 없으면 undefined */
  location?: string;
}

/** 스택을 원본 위치로 바꾸는 함수 */
export type StackMapper = (stack: string) => MappedStack;

function readSourceMaps(dir: string | undefined, sink: LogSink): Map<string, SourceMap> {
  const maps = new Map<string, SourceMap>();
  if (dir === undefined) {
    return maps;
  }
  try {
    for (const name of readdirSync(dir)) {
      if (name.endsWith(".js.map")) {
        // 이 프로젝트의 빌드가 만든 파일이라 형식을 믿는다
        const payload = JSON.parse(readFileSync(path.join(dir, name), "utf8")) as SourceMapPayload;
        // 위치만 찾으면 되므로 원본 코드 내용은 메모리에 두지 않는다
        maps.set(name.slice(0, -".map".length), new SourceMap({ ...payload, sourcesContent: [] }));
      }
    }
  } catch (e) {
    sink.write({
      level: "warn",
      message: "소스맵을 읽지 못해 스택을 빌드 위치 그대로 남긴다",
      fields: { cause: String(e) },
    });
  }
  return maps;
}

/**
 * 스택 변환 함수를 만든다.
 *
 * @param dir *.js.map 이 있는 폴더. 없거나 읽지 못하면 스택을 그대로 돌려준다
 * @param sink 소스맵을 읽지 못한 원인을 남길 곳
 */
export function createStackMapper(dir: string | undefined, sink: LogSink): StackMapper {
  const maps = readSourceMaps(dir, sink);

  return (stack) => {
    const locations: string[] = [];
    const mapped = stack.replace(
      FRAME_LOCATION,
      (original, file: string, line: string, column: string) => {
        // 스택의 줄 · 칸은 1부터, 소스맵은 0부터 센다
        const entry = maps.get(file)?.findEntry(Number(line) - 1, Number(column) - 1);
        if (entry === undefined || !("originalSource" in entry)) {
          return original;
        }
        const source = entry.originalSource.replace(/^(?:\.\.\/)+/, "");
        locations.push(`${source}:${entry.originalLine + 1}`);
        return `${source}:${entry.originalLine + 1}:${entry.originalColumn + 1}`;
      },
    );
    const location =
      locations.find((item) => item.startsWith(APP_SOURCE_PREFIX)) ?? locations.at(0);
    return { stack: mapped, location };
  };
}
