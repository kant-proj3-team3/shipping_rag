import { SealFace } from "./SealFace";
import { SealSilhouette } from "./SealSilhouette";
import { SEAL_INK, useSealSvg, type SealProps } from "./useSealSvg";

const HEAD_X = 54;
const HEAD_Y = 56;
const BODY_PATH = "M 24 66 C 16 82 18 98 28 104 L 82 104 C 90 96 90 80 82 68 Z";

/** 네 꼭짓점 반짝임 (가운데 x · y, 반지름 r) */
function sparklePath(x: number, y: number, r: number): string {
  return `M ${x} ${y - r} Q ${x} ${y} ${x + r} ${y} Q ${x} ${y} ${x} ${y + r} Q ${x} ${y} ${x - r} ${y} Q ${x} ${y} ${x} ${y - r} Z`;
}

const BIG_SPARKLE = sparklePath(104, 18, 9);
const SMALL_SPARKLE = sparklePath(117, 33, 5.5);

/**
 * 펼친 책 뒤에서 연필을 든 물개: LLM 머리띠, 옆에 쌓인 책.
 * 움직이면 연필로 쓰고 눈을 깜박이며 오른쪽 위 별이 반짝인다
 */
export function SealStudy({ isAnimated, className }: SealProps) {
  const svg = useSealSvg({ isAnimated, className });

  return (
    <svg viewBox="0 0 128 128" aria-hidden="true" className={svg.svgClass}>
      <g fill="#ffd23f" stroke="#e9b021" strokeWidth="1" strokeLinejoin="round">
        <g className="origin-center transform-fill motion-safe:animate-seal-twinkle">
          <path d={BIG_SPARKLE} />
        </g>
        <g className="origin-center transform-fill motion-safe:animate-seal-twinkle-late">
          <path d={SMALL_SPARKLE} />
        </g>
      </g>

      <g className="origin-[54px_104px] transform-view motion-safe:animate-seal-bob">
        <SealSilhouette svg={svg} headX={HEAD_X} headY={HEAD_Y} body={BODY_PATH} />
        <SealFace svg={svg} headX={HEAD_X} headY={HEAD_Y} eyes="open" mouth="smile" />
      </g>

      <g stroke={SEAL_INK} strokeWidth="1.8" strokeLinejoin="round">
        <rect x="86" y="104" width="38" height="13" rx="3.5" fill="#a8c8f7" />
        <rect x="89" y="93" width="33" height="11" rx="3.5" fill="#ffffff" />
        <rect x="87" y="82" width="36" height="11" rx="3.5" fill="#ffd76a" />
      </g>
      <g fill="none" strokeWidth="1.4" strokeLinecap="round">
        <path d="M 92 110.5 H 114" stroke="#7ea6e6" />
        <path d="M 95 98.5 H 114" stroke="#c9d3e6" />
        <path d="M 93 87.5 H 115" stroke="#e3b24a" />
      </g>

      <path
        fill="#3f73e6"
        stroke={SEAL_INK}
        strokeWidth="2"
        strokeLinejoin="round"
        d="M 6 96 C 24 92 42 94 56 101 C 70 94 88 92 104 96 L 106 121 C 88 117 70 118 56 124 C 42 118 24 117 4 121 Z"
      />
      <g fill="#fbfcff" stroke={SEAL_INK} strokeWidth="1.8" strokeLinejoin="round">
        <path d="M 9 93 C 26 88 43 90 56 98 L 56 119 C 43 113 26 112 8 116 Z" />
        <path d="M 103 93 C 86 88 69 90 56 98 L 56 119 C 69 113 86 112 104 116 Z" />
      </g>
      <g fill="none" stroke="#b9c7e2" strokeWidth="1.2" strokeLinecap="round">
        <path d="M 16 99 C 28 96 40 97 50 102" />
        <path d="M 16 105 C 28 102 40 103 50 108" />
        <path d="M 62 102 C 72 97 84 96 96 99" />
        <path d="M 62 108 C 72 103 84 102 96 105" />
      </g>

      <g className="origin-[20px_80px] transform-view motion-safe:animate-seal-write">
        <g stroke={SEAL_INK} strokeWidth="1.6" strokeLinejoin="round" transform="rotate(-28 20 74)">
          <rect x="17" y="46" width="6" height="5" rx="1.5" fill="#f29aa6" />
          <rect x="17" y="50" width="6" height="28" fill="#ffd23f" />
          <path d="M 17 78 L 23 78 L 20 86 Z" fill="#f6d7a7" />
          <path d="M 19 83.4 L 21 83.4 L 20 86 Z" fill={SEAL_INK} />
        </g>
        <path
          fill={svg.url("fur")}
          stroke={SEAL_INK}
          strokeWidth="2.2"
          strokeLinejoin="round"
          d="M 10 84 C 6 74 12 66 21 67 C 30 68 33 77 30 85 C 27 92 14 92 10 84 Z"
        />
      </g>
    </svg>
  );
}
