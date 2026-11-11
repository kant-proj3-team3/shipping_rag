import { SealFace } from "./SealFace";
import { SealSilhouette } from "./SealSilhouette";
import { SEAL_INK, useSealSvg, type SealProps } from "./useSealSvg";

const HEAD_X = 64;
const HEAD_Y = 62;
const BODY_PATH = "M 36 76 C 28 94 31 113 46 119 C 60 124 74 124 88 119 C 102 112 104 94 94 78 Z";

/** 응원 술 바깥선: 원 둘레를 작은 호로 이어 복슬복슬하게 만든다 (가운데 x · y, 반지름 r, 호 개수 n) */
function pomPomPath(x: number, y: number, r: number, n: number): string {
  const step = (Math.PI * 2) / n;
  // 이웃한 두 점 사이 거리보다 조금 큰 반지름이라 호가 바깥으로 부푼다
  const bump = (r * Math.sin(step / 2) * 1.15).toFixed(2);
  const point = (i: number): string =>
    `${(x + r * Math.cos(i * step)).toFixed(2)} ${(y + r * Math.sin(i * step)).toFixed(2)}`;
  const arcs = Array.from({ length: n }, (_, i) => `A ${bump} ${bump} 0 0 1 ${point(i + 1)}`);
  return `M ${point(0)} ${arcs.join(" ")} Z`;
}

/** 하트 (가운데 x · y, 크기 s) */
function heartPath(x: number, y: number, s: number): string {
  return `M ${x} ${y + s * 0.8} C ${x - s * 1.3} ${y} ${x - s * 0.9} ${y - s} ${x} ${y - s * 0.35} C ${x + s * 0.9} ${y - s} ${x + s * 1.3} ${y} ${x} ${y + s * 0.8} Z`;
}

const LEFT_POM = pomPomPath(26, 80, 13, 11);
const RIGHT_POM = pomPomPath(104, 94, 13, 11);
const BIG_HEART = heartPath(104, 22, 8);
const SMALL_HEART = heartPath(117, 37, 5);

/**
 * 응원 술을 흔드는 물개: LLM 머리띠, 질끈 감은 눈, "화이팅!".
 * 움직이면 양손의 응원 술을 번갈아 흔들고 몸이 들썩이며 하트가 떠오른다
 */
export function SealCheer(props: SealProps) {
  const svg = useSealSvg(props);

  return (
    <svg viewBox="0 0 128 128" aria-hidden="true" className={svg.svgClass}>
      <g fill="none" stroke="#ffcf3a" strokeWidth="2.8" strokeLinecap="round">
        <path d="M 7 27 l -4.5 -3" />
        <path d="M 10 21 l -3.5 -4.5" />
      </g>
      <g className="origin-center transform-fill motion-safe:animate-seal-pop">
        <text
          x="13"
          y="24"
          transform="rotate(-10 34 18)"
          fontSize="15"
          fontWeight="900"
          fill="#2f62d6"
          stroke="#ffffff"
          strokeWidth="3"
          strokeLinejoin="round"
          paintOrder="stroke"
        >
          화이팅!
        </text>
      </g>
      <g fill="#f39aa8">
        <g className="motion-safe:animate-seal-float">
          <path d={BIG_HEART} />
        </g>
        <g className="motion-safe:animate-seal-float-late">
          <path d={SMALL_HEART} />
        </g>
      </g>

      <g className="origin-[64px_122px] transform-view motion-safe:animate-seal-hop">
        <SealSilhouette svg={svg} headX={HEAD_X} headY={HEAD_Y} body={BODY_PATH} />
        <SealFace svg={svg} headX={HEAD_X} headY={HEAD_Y} eyes="squint" mouth="open" />

        {/* 응원 술은 손에 쥔 채 손 앞에 온다: 손을 먼저 그리고 술로 덮는다 */}
        <g className="origin-[36px_90px] transform-view motion-safe:animate-seal-shake">
          <path
            fill={svg.url("fur")}
            stroke={SEAL_INK}
            strokeWidth="2.2"
            strokeLinejoin="round"
            d="M 31 96 C 27 88 31 82 38 82 C 45 83 47 92 43 98 C 40 102 33 101 31 96 Z"
          />
          <path d={LEFT_POM} fill="#ffd84a" stroke={SEAL_INK} strokeWidth="1.8" />
          <g fill="none" stroke="#e7b52b" strokeWidth="1.3" strokeLinecap="round">
            <path d="M 22 74 l -3 -3 M 28 72 l 1 -4 M 20 84 l -4 1 M 31 80 l 4 -1" />
          </g>
        </g>
        <g className="origin-[94px_102px] transform-view motion-safe:animate-seal-shake-late">
          <path
            fill={svg.url("fur")}
            stroke={SEAL_INK}
            strokeWidth="2.2"
            strokeLinejoin="round"
            d="M 87 106 C 84 98 88 92 95 92 C 102 93 104 102 100 108 C 97 112 89 111 87 106 Z"
          />
          <path d={RIGHT_POM} fill="#ffd84a" stroke={SEAL_INK} strokeWidth="1.8" />
          <g fill="none" stroke="#e7b52b" strokeWidth="1.3" strokeLinecap="round">
            <path d="M 100 88 l -3 -3 M 107 86 l 1 -4 M 110 96 l 4 1 M 100 100 l -2 4" />
          </g>
        </g>
      </g>
    </svg>
  );
}
