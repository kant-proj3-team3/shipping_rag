import { useId } from "react";

/** 물개 그림의 머리 반지름 (viewBox 0 0 128 128 기준). 몸 실루엣과 얼굴이 같은 원을 쓴다 */
export const SEAL_HEAD_RADIUS = 32;

/** 물개 그림의 선 색 */
export const SEAL_INK = "#2a1c1c";

// 물개 그림이 움직이는 때: still 멈춤 · always 늘 · hover 마우스를 올린 동안만
type SealMotion = "still" | "always" | "hover";

/** 물개 그림 공통 속성 */
export interface SealProps {
  /** 움직이는 때 (still · always · hover). 기본은 멈춘 그림이다 (움직임 줄이기 설정에서는 늘 멈춘다) */
  motion?: SealMotion;
  /**
   * 움직임을 손 · 눈 깜박임 · 반짝임만 남기고 몸 들썩임 · 머리띠 · 소품은 멈춘다. 반짝임은 크기는 그대로 두고 밝기만 바뀐다.
   * 작게 그리면 몸 전체처럼 큰 선이 움직일 때 픽셀 사이에 걸려 흐려 보이므로 작은 그림에 쓴다
   */
  isSubtle?: boolean;
  /** 크기 · 배치 (예: "size-16") */
  className?: string;
}

/** 물개 그림 하나 안에서 쓰는 id 도우미와 svg class */
export interface SealSvg {
  /** 그림마다 다른 id. 한 화면에 여러 그림이 있어도 그라데이션 · 마스크가 겹치지 않는다 */
  id: (name: string) => string;
  /** id 를 가리키는 url(#…) */
  url: (name: string) => string;
  /** svg 에 붙일 class. 멈춘 그림이면 안쪽 움직임을 모두 끈다 */
  svgClass: string;
}

// 잔잔한 움직임: 손 · 눈 깜박임 · 반짝임 말고는 끄고, 반짝임은 keyframes 이름만 밝기 변화(seal-glow, index.css)로 바꾼다.
// 이름만 바꾸므로 반짝임마다 어긋난 시작 시점은 그대로다
const SUBTLE_CLASS =
  "[&_:not([data-seal-paw]):not([data-seal-blink]):not([data-seal-spark])]:animate-none! motion-safe:[&_[data-seal-spark]]:[animation-name:seal-glow]";

// 움직이는 때에 따라 안쪽 움직임을 끄는 class (motion-safe 애니메이션보다 앞서도록 important).
// 멈춘 그림은 모두 끄고, 마우스를 올리면 움직이는 그림은 마우스가 올라와 있지 않을 때만 끈다
const STILL_CLASS: Record<SealMotion, string> = {
  still: "[&_*]:animate-none!",
  always: "",
  hover: "[&:not(:hover)_*]:animate-none!",
};

/**
 * 물개 그림의 id 와 class 를 만든다.
 * id 가 겹치면 앞의 그림이 숨겨질 때 뒤 그림의 색이 사라지므로 그림마다 접두어를 붙인다.
 * 손 그룹에는 data-seal-paw, 눈 깜박임 그룹에는 data-seal-blink, 반짝임 그룹에는 data-seal-spark 를 붙인다
 * (isSubtle 이 이 셋만 남긴다)
 */
export function useSealSvg({
  motion = "still",
  isSubtle = false,
  className = "",
}: SealProps): SealSvg {
  // id 를 url() 에 넣으므로 영문 · 숫자만 남긴다
  const prefix = `seal${useId().replace(/[^\w-]/g, "")}`;
  const subtleClass = isSubtle ? SUBTLE_CLASS : "";
  return {
    id: (name) => `${prefix}-${name}`,
    url: (name) => `url(#${prefix}-${name})`,
    svgClass: `${className} ${STILL_CLASS[motion]} ${subtleClass}`,
  };
}
