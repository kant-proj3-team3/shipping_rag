import { SealFace } from "./SealFace";
import { SealSilhouette } from "./SealSilhouette";
import { SEAL_INK, useSealSvg, type SealProps } from "./useSealSvg";

const HEAD_X = 64;
const HEAD_Y = 52;
const BODY_PATH = "M 36 66 C 26 84 28 110 44 117 C 58 123 72 123 86 117 C 102 110 104 84 92 66 Z";

/**
 * 금화를 두 손으로 꼭 안은 물개: LLM 머리띠, 웃는 눈.
 * 움직이면 금화를 든 손이 들썩이고 금화가 반짝이며 왼쪽 위 반짝임이 깜박인다
 */
export function SealCoin(props: SealProps) {
  const svg = useSealSvg(props);

  return (
    <svg viewBox="0 0 128 128" aria-hidden="true" className={svg.svgClass}>
      <defs>
        <linearGradient id={svg.id("coin")} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffe08a" />
          <stop offset="1" stopColor="#f2b23a" />
        </linearGradient>
      </defs>

      <g fill="none" stroke="#ffcf3a" strokeWidth="3.2" strokeLinecap="round">
        <g data-seal-spark className="origin-center transform-fill motion-safe:animate-seal-spark">
          <path d="M 17 31 l -7 -3" />
        </g>
        <g
          data-seal-spark
          className="origin-center transform-fill motion-safe:animate-seal-spark-2"
        >
          <path d="M 21 22 l -5 -6" />
        </g>
        <g
          data-seal-spark
          className="origin-center transform-fill motion-safe:animate-seal-spark-3"
        >
          <path d="M 29.5 17 l -1.5 -7.5" />
        </g>
      </g>

      <g className="origin-[64px_120px] transform-view motion-safe:animate-seal-bob">
        <SealSilhouette svg={svg} headX={HEAD_X} headY={HEAD_Y} body={BODY_PATH} />
        <SealFace svg={svg} headX={HEAD_X} headY={HEAD_Y} eyes="happy" mouth="smile" />

        <g data-seal-paw className="motion-safe:animate-seal-hug">
          <circle cx="64" cy="91" r="15" fill={svg.url("coin")} stroke={SEAL_INK} strokeWidth="2" />
          <circle cx="64" cy="91" r="11" fill="none" stroke="#d99a2b" strokeWidth="1.6" />
          <path
            fill="none"
            stroke="#b07818"
            strokeWidth="3"
            strokeLinecap="round"
            d="M 58.6 85.6 H 69.4 M 64 85.6 V 97"
          />
          <path
            fill="none"
            stroke="#ffffff"
            strokeWidth="1.6"
            strokeLinecap="round"
            opacity="0.75"
            d="M 54.5 87.5 A 10.5 10.5 0 0 1 60 81.4"
          />
          <g className="origin-center transform-fill motion-safe:animate-seal-glint">
            <path
              fill="#ffffff"
              d="M 71 81 Q 71.4 84.6 75 85 Q 71.4 85.4 71 89 Q 70.6 85.4 67 85 Q 70.6 84.6 71 81 Z"
            />
          </g>
          <g fill={svg.url("fur")} stroke={SEAL_INK} strokeWidth="2.2" strokeLinejoin="round">
            <path d="M 44 98 C 41 88 46 81 53 82 C 58 83 58 95 54 101 C 51 105 45 104 44 98 Z" />
            <path d="M 84 98 C 87 88 82 81 75 82 C 70 83 70 95 74 101 C 77 105 83 104 84 98 Z" />
          </g>
        </g>
      </g>
    </svg>
  );
}
