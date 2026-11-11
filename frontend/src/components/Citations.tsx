import type { Citation } from "../api/types";

/** 출처 한 줄 (같은 문서 · 쪽은 한 번만) */
interface CitationItem {
  key: string;
  fileName: string;
  page: number;
}

interface CitationsProps {
  citations: Citation[];
}

function uniqueByPage(citations: Citation[]): CitationItem[] {
  const seen = new Map<string, CitationItem>();
  for (const { fileName, page } of citations) {
    const key = `${fileName}#${page}`;
    if (!seen.has(key)) {
      seen.set(key, { key, fileName, page });
    }
  }
  return [...seen.values()];
}

/** 출처 목록: "IS12.pdf 9쪽" 꼴. source_id 는 요청 안에서만 유효해 보여 주지 않는다 */
export function Citations({ citations }: CitationsProps) {
  const items = uniqueByPage(citations);
  if (items.length === 0) {
    return <p className="text-zinc-500">출처 없음</p>;
  }
  return (
    <ul className="flex flex-wrap gap-1.5">
      {items.map(({ key, fileName, page }) => (
        <li
          key={key}
          className="rounded-md border border-zinc-200 px-2 py-0.5 text-xs text-zinc-700 dark:border-zinc-700 dark:text-zinc-300"
        >
          {fileName} {page}쪽
        </li>
      ))}
    </ul>
  );
}
