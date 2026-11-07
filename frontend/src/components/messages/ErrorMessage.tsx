interface ErrorMessageProps {
  /** 사용자용 안내. 오류 코드는 로그용이라 보여 주지 않는다 */
  text: string;
}

/** 오류 안내: 빨간 상자 한 줄 */
export function ErrorMessage({ text }: ErrorMessageProps) {
  return (
    <p
      role="alert"
      className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-800 dark:border-red-900 dark:bg-red-950/50 dark:text-red-300"
    >
      {text}
    </p>
  );
}
