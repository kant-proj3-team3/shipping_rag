import { Component, type ReactNode } from "react";

interface ErrorBoundaryProps {
  /** 안에서 예외가 나면 보여 줄 안내 */
  message: string;
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

// 렌더 중 예외를 잡는 API 가 클래스에만 있어 클래스로 둔다. 원인은 React 가 콘솔에 남긴다
/**
 * 렌더 중 예외를 잡아 안내와 새로고침 버튼으로 바꾼다 (빈 화면이 되지 않게).
 * 다시 시도하게 하려면 key 를 바꿔 새로 만든다.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  override render() {
    const { message, children } = this.props;
    if (!this.state.hasError) {
      return children;
    }
    return (
      <div
        role="alert"
        className="flex h-full min-h-0 flex-1 flex-col items-center justify-center gap-3 p-6 text-center text-sm text-zinc-600 dark:text-zinc-400"
      >
        <p>{message}</p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="rounded-lg border border-zinc-300 px-3 py-1.5 text-xs font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          새로고침
        </button>
      </div>
    );
  }
}
