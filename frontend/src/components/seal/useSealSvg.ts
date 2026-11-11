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

// 움직이는 때에 따라 안쪽 움직임을 끄는 class (motion-safe 애니메이션보다 앞서도록 important).
// 멈춘 그림은 모두 끄고, 마우스를 올리면 움직이는 그림은 마우스가 올라와 있지 않을 때만 끈다
const STILL_CLASS: Record<SealMotion, string> = {
  still: "[&_*]:animate-none!",
  always: "",
  hover: "[&:not(:hover)_*]:animate-none!",
};

/**
 * 물개 그림의 id 와 class 를 만든다.
 * id 가 겹치면 앞의 그림이 숨겨질 때 뒤 그림의 색이 사라지므로 그림마다 접두어를 붙인다
 */
export function useSealSvg({ motion = "still", className = "" }: SealProps): SealSvg {
  // id 를 url() 에 넣으므로 영문 · 숫자만 남긴다
  const prefix = `seal${useId().replace(/[^\w-]/g, "")}`;
  return {
    id: (name) => `${prefix}-${name}`,
    url: (name) => `url(#${prefix}-${name})`,
    svgClass: `${className} ${STILL_CLASS[motion]}`,
  };
}
