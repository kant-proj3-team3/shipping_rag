import { SEAL_HEAD_RADIUS, SEAL_INK, type SealSvg } from "./useSealSvg";

interface SealSilhouetteProps {
  svg: SealSvg;
  /** 머리 원의 중심 (viewBox 좌표) */
  headX: number;
  headY: number;
  /** 머리 아래로 이어지는 몸통 path. 머리 원과 겹쳐도 된다 */
  body: string;
}

/**
 * 머리와 몸통을 한 덩어리로 그린다. 둘이 겹친 곳의 선은 숨기고 바깥 선만 남긴다.
 * 털 그라데이션 fur 를 여기서 정의하므로 지느러미도 svg.url("fur") 로 같은 색을 쓴다
 */
export function SealSilhouette({ svg, headX, headY, body }: SealSilhouetteProps) {
  const shapes = (
    <>
      <circle cx={headX} cy={headY} r={SEAL_HEAD_RADIUS} />
      <path d={body} />
    </>
  );
  return (
    <>
      <defs>
        <linearGradient
          id={svg.id("fur")}
          gradientUnits="userSpaceOnUse"
          x1="0"
          y1="20"
          x2="0"
          y2="124"
        >
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="0.65" stopColor="#fbfafb" />
          <stop offset="1" stopColor="#e6e4f2" />
        </linearGradient>
      </defs>
      {/* 선을 두 배 굵기로 먼저 그리고 그 위를 털 색으로 덮어, 바깥쪽 절반만 선으로 남긴다 */}
      <g fill={SEAL_INK} stroke={SEAL_INK} strokeWidth="4.4" strokeLinejoin="round">
        {shapes}
      </g>
      <g fill={svg.url("fur")}>{shapes}</g>
    </>
  );
}
