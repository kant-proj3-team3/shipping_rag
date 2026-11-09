// 하루에 남길 로그 양을 묶는다. 요청이 몰려도 날짜별 로그가 밀려나지 않게 한다.

/** allowed: 남긴다. just_exhausted: 이번에 한도를 넘었다. exhausted: 이미 넘은 상태다 */
type QuotaResult = "allowed" | "just_exhausted" | "exhausted";

interface DailyQuota {
  /** 남기려는 양을 더하고 결과를 돌려준다. 날짜가 바뀌면 새로 센다 */
  take: (bytes: number) => QuotaResult;
}

/** 하루치 한도를 만든다. 프로세스가 다시 시작되면 그날 쓴 양도 처음부터 다시 센다 */
export function createDailyQuota(limitBytes: number): DailyQuota {
  let day = "";
  let used = 0;

  function take(bytes: number): QuotaResult {
    const today = new Date().toDateString();
    if (today !== day) {
      day = today;
      used = 0;
    }
    const before = used;
    used += bytes;
    if (used <= limitBytes) {
      return "allowed";
    }
    return before <= limitBytes ? "just_exhausted" : "exhausted";
  }

  return { take };
}
