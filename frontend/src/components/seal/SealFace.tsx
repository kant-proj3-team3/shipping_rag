import { SEAL_HEAD_RADIUS, SEAL_INK, type SealSvg } from "./useSealSvg";

/** 머리띠 가운데 선 (머리 중심 기준). 머리 원 밖까지 그리고 원으로 잘라 낸다. 글자도 이 선을 따라 쓴다 */
const BAND_PATH = "M -38 -8 Q 0 -31 40 -4";

/** 눈 모양: 뜬 눈 · 웃는 눈(^ ^) · 질끈 감은 눈(> <) */
type SealEyes = "open" | "happy" | "squint";
/** 입 모양: 벌린 입 · 다문 입 */
type SealMouth = "open" | "smile";

interface SealFaceProps {
  svg: SealSvg;
  /** 머리 원의 중심 (viewBox 좌표). SealSilhouette 와 같은 값을 준다 */
  headX: number;
  headY: number;
  eyes: SealEyes;
  mouth: SealMouth;
}

interface EyesProps {
  svg: SealSvg;
  eyes: SealEyes;
}

function Eyes({ svg, eyes }: EyesProps) {
  if (eyes === "happy") {
    return (
      <path
        fill="none"
        stroke={SEAL_INK}
        strokeWidth="2.2"
        strokeLinecap="round"
        d="M -16.5 3.5 Q -12 -2.5 -7.5 3.5 M 7.5 3.5 Q 12 -2.5 16.5 3.5"
      />
    );
  }
  if (eyes === "squint") {
    return (
      <path
        fill="none"
        stroke={SEAL_INK}
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M -16 -2 L -9.5 2.5 L -16 7 M 16 -2 L 9.5 2.5 L 16 7"
      />
    );
  }
  return (
    <>
      <g fill="none" stroke="#9aa0b4" strokeWidth="1.5" strokeLinecap="round">
        <path d="M -15.5 -7.5 l 4 -1.4" />
        <path d="M 11.5 -8.9 l 4 1.4" />
      </g>
      <g className="origin-center transform-fill motion-safe:animate-seal-blink">
        <ellipse cx="-12.5" cy="2" rx="5" ry="5.6" fill={svg.url("iris")} />
        <ellipse cx="12.5" cy="2" rx="5" ry="5.6" fill={svg.url("iris")} />
        <g fill="#ffffff">
          <circle cx="-14" cy="-0.2" r="1.9" />
          <circle cx="-11.2" cy="4.6" r="0.85" />
          <circle cx="11" cy="-0.2" r="1.9" />
          <circle cx="13.8" cy="4.6" r="0.85" />
        </g>
      </g>
    </>
  );
}

function OpenMouth() {
  return (
    <>
      <path
        fill="#e35d68"
        stroke={SEAL_INK}
        strokeWidth="1.4"
        strokeLinejoin="round"
        d="M -4.6 13.4 C -5 21.8 5 21.8 4.6 13.4 Q 2.4 14.4 0 12.6 Q -2.4 14.4 -4.6 13.4 Z"
      />
      <path fill="#f7a39b" d="M -3.2 18.2 Q 0 15.8 3.2 18.2 C 2.2 20.2 -2.2 20.2 -3.2 18.2 Z" />
    </>
  );
}

/**
 * LLM 머리띠를 두른 물개 얼굴. 머리 원 위에 눈 · 코 · 입 · 볼 · 수염 · 머리띠를 그린다.
 * 머리 모양(원)은 SealSilhouette 가 그린다
 */
export function SealFace({ svg, headX, headY, eyes, mouth }: SealFaceProps) {
  return (
    <g transform={`translate(${headX} ${headY})`}>
      <defs>
        <clipPath id={svg.id("head")}>
          <circle r={SEAL_HEAD_RADIUS} />
        </clipPath>
        <linearGradient id={svg.id("band")} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#3f73e6" />
          <stop offset="1" stopColor="#2450c2" />
        </linearGradient>
        <radialGradient id={svg.id("iris")} cx="0.5" cy="0.85" r="0.75">
          <stop offset="0" stopColor="#4a6fc9" />
          <stop offset="1" stopColor="#1b1a33" />
        </radialGradient>
        <path id={svg.id("band-line")} d={BAND_PATH} />
      </defs>

      <g fill="#f7b9b4" opacity="0.85">
        <ellipse cx="-21" cy="10" rx="5.6" ry="3.6" />
        <ellipse cx="21" cy="10" rx="5.6" ry="3.6" />
      </g>
      <g fill="none" stroke={SEAL_INK} strokeWidth="1.1" strokeLinecap="round">
        <path d="M -24 8.5 l -9 -1.6 M -24.5 12 l -8.6 1.8" />
        <path d="M 24 8.5 l 9 -1.6 M 24.5 12 l 8.6 1.8" />
      </g>

      <Eyes svg={svg} eyes={eyes} />

      {mouth === "open" ? <OpenMouth /> : null}
      <path
        fill="none"
        stroke={SEAL_INK}
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M -6 11.4 Q -3 15.4 0 11.8 Q 3 15.4 6 11.4"
      />
      <ellipse cx="0" cy="8.4" rx="2.8" ry="1.9" fill={SEAL_INK} />
      <ellipse cx="-0.8" cy="7.8" rx="0.8" ry="0.45" fill="#ffffff" opacity="0.8" />

      <g clipPath={svg.url("head")}>
        <path d={BAND_PATH} fill="none" stroke="#14224f" strokeWidth="14" />
        <path d={BAND_PATH} fill="none" stroke={svg.url("band")} strokeWidth="10.6" />
      </g>
      <text fontSize="9.5" fontWeight="800" fill="#ffffff" letterSpacing="0.6">
        <textPath
          href={`#${svg.id("band-line")}`}
          startOffset="42%"
          textAnchor="middle"
          dominantBaseline="central"
        >
          LLM
        </textPath>
      </text>
      <path
        fill="#ffffff"
        transform="translate(11.5 -16.6) rotate(13)"
        d="M 0 3 C -4.4 0 -4 -3.6 -1.6 -3.6 C -0.6 -3.6 0 -2.8 0 -2 C 0 -2.8 0.6 -3.6 1.6 -3.6 C 4 -3.6 4.4 0 0 3 Z"
      />

      <g
        className="origin-left transform-fill motion-safe:animate-seal-wag"
        fill={svg.url("band")}
        stroke="#14224f"
        strokeWidth="1.8"
        strokeLinejoin="round"
      >
        <path d="M 30 -8 C 36 -18 46 -17 48 -10 C 45 -6 38 -5 31 -5 Z" />
        <path d="M 30 -4 C 37 -1 45 7 42 13 C 37 13 33 5 30 -1 Z" />
        <circle cx="31" cy="-5" r="3.6" />
      </g>
    </g>
  );
}
