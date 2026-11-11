/** 팀 이름. 로고 글자와 같다 */
const TEAM_NAME = "엘키해적단";

/** 글자 획: 굵고 각진 획으로 그린다 (글자 하나는 가로 21 · 세로 24 칸) */
const LETTER_STROKE = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 3,
  strokeLinecap: "square",
  strokeLinejoin: "miter",
} as const;

/** 배 아래 물결 (떠 있을 때) */
const WAVE_PATH = "M3 36.5q3-2 6 0t6 0 6 0 6 0 6 0 4 0";

/** 가라앉을 때 수면. 배가 잠기도록 물결을 위로 올린다 */
const SINKING_WAVE_PATH = "M2 30q3-2 6 0t6 0 6 0 6 0 6 0 6 0";

/** 가라앉을 때 수면 아래 물. 배의 잠긴 부분을 덮는다 */
const SINKING_WATER_PATH = `${SINKING_WAVE_PATH}V40H2Z`;

/** 가라앉을 때 배를 오른쪽으로 기울여 물속으로 내린다 (돛대 · 돛 · 배 전체) */
const SINKING_TRANSFORM = "translate(0 6) rotate(25 20 30)";

interface PirateShipProps {
  /** 옆으로 기울어 가라앉는 모양으로 그린다 */
  isSinking: boolean;
}

// 해적선: 흰 돛에 한쪽 눈에 안대를 한 엘키 얼굴을 그리고 돛대 끝에 검은 깃발을 단 배.
// 돛대 · 깃발 · 배 · 물은 어두운 테마에서 밝게 바꾼다
function PirateShip({ isSinking }: PirateShipProps) {
  return (
    <svg viewBox="0 0 40 40" aria-hidden="true" className="w-9 shrink-0">
      <g transform={isSinking ? SINKING_TRANSFORM : undefined}>
        <path d="M20 3v24" strokeWidth="1.6" className="stroke-[#2a1c1c] dark:stroke-zinc-300" />
        <path d="M20 3.5l7 2.2-7 2.3z" className="fill-[#2a1c1c] dark:fill-zinc-300" />
        <circle cx="23" cy="5.7" r="0.8" fill="#ffd84a" />
        <path
          d="M10.5 10Q20 7.5 29.5 10L28.5 23Q20 25 11.5 23Z"
          fill="#ffffff"
          stroke="#14224f"
          strokeWidth="1"
        />
        <ellipse cx="17" cy="15.5" rx="1.2" ry="1.4" fill="#1b1a33" />
        <path d="M11.2 11.6L29 16.4" stroke="#2a1c1c" strokeWidth="0.7" />
        <ellipse cx="23.2" cy="15.6" rx="2" ry="1.8" fill="#2a1c1c" />
        <ellipse cx="20" cy="18.3" rx="1.3" ry="0.85" fill="#2a1c1c" />
        <g fill="#f9c9c4">
          <ellipse cx="14.6" cy="18.6" rx="1.3" ry="0.8" />
          <ellipse cx="25.4" cy="18.6" rx="1.3" ry="0.8" />
        </g>
        <path d="M4.5 26.5h31l-4.5 7h-22z" className="fill-[#16328a] dark:fill-[#2f5fd3]" />
        <path d="M6 28.5h28" stroke="#ffd84a" strokeWidth="0.9" />
      </g>
      {isSinking ? (
        <path d={SINKING_WATER_PATH} className="fill-[#dbe7ff] dark:fill-[#1e3a6e]" />
      ) : null}
      <path
        d={isSinking ? SINKING_WAVE_PATH : WAVE_PATH}
        fill="none"
        strokeWidth="1.6"
        strokeLinecap="round"
        className="stroke-[#2450c2] dark:stroke-[#9db8ff]"
      />
    </svg>
  );
}

// 팀 이름 글자. 글꼴 파일 없이 어디서나 같은 모양이 되도록 획을 직접 그린다. "엘키"는 파란색으로 강조한다
function Wordmark() {
  return (
    <svg viewBox="0 0 104 24" role="img" aria-label={TEAM_NAME} className="h-5 w-auto">
      <g {...LETTER_STROKE} className="text-[#2450c2] dark:text-[#9db8ff]">
        <circle cx="4.8" cy="5.4" r="3" />
        <path d="M11 5.4H12.8M12.8 1.6V9.6M17.4 1.5V10M3.2 13.4H16.6V17.7H3.4V22H17" />
        <path transform="translate(21 0)" d="M2.4 4H10.4Q10.4 15 2.6 20.5M2.8 11H9.6M16 1.6V22.4" />
      </g>
      <g {...LETTER_STROKE} className="text-[#2a1c1c] dark:text-zinc-100">
        <g transform="translate(42 0)">
          <path d="M4 2H8M1.8 6.2H10.2M12.8 1.6V22.4M12.8 11H17.4M17.4 1.6V22.4" />
          <circle cx="6" cy="14" r="4.2" />
        </g>
        <path
          transform="translate(63 0)"
          d="M2 2.4H9.8M5.9 2.6Q5.4 7 1.8 10M6.2 5.8Q7.6 8.6 10.2 10M11.6 6H15.6M15.6 1.6V10.6M3 13.4H16.6V22.2"
        />
        <path
          transform="translate(84 0)"
          d="M10.2 2H2.6V9.6H10.4M13.6 1.6V10.8M13.6 6H17.4M3 13.2V21.2H17.2"
        />
      </g>
    </svg>
  );
}

interface TeamLogoProps {
  /** 배를 옆으로 기울어 가라앉는 모양으로 그린다 (서버가 정상이 아닐 때). 기본은 떠 있는 배 */
  isSinking?: boolean;
}

/** 팀 로고 "엘키해적단": 엘키 얼굴 돛을 단 해적선과 직접 그린 굵은 글자 */
export function TeamLogo({ isSinking = false }: TeamLogoProps) {
  return (
    <div className="flex items-center gap-2">
      <PirateShip isSinking={isSinking} />
      <Wordmark />
    </div>
  );
}
