import { useSealSvg, type SealProps } from "./useSealSvg";

/**
 * 마스코트 물개 그림: "오늘도 해내자!" 머리띠를 두르고 양손을 든 모습.
 *
 * 옆의 글이 설명을 맡으므로 스크린 리더에는 숨긴다.
 */
export function SealMascot({ isAnimated, className }: SealProps) {
  const { id, url, svgClass } = useSealSvg({ isAnimated, className });

  return (
    <svg viewBox="0 0 128 128" aria-hidden="true" className={svgClass}>
      <defs>
        <linearGradient id={id("fade-ramp")} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0.76" stopColor="#ffffff" />
          <stop offset="1" stopColor="#000000" />
        </linearGradient>
        <mask id={id("fade")} maskUnits="userSpaceOnUse" x="0" y="0" width="128" height="128">
          <rect width="128" height="128" fill={url("fade-ramp")} />
        </mask>
        <clipPath id={id("mouth")}>
          <path d="M48.5 78C52 77.5 57 74 59 71c2 3 5 5 8.5 5.5C67 84 62 91.5 56 91.5c-5.5 0-8.5-7.5-7.5-13.5Z" />
        </clipPath>
        <linearGradient id={id("fur")} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="0.65" stopColor="#fbfafb" />
          <stop offset="1" stopColor="#e6e4f2" />
        </linearGradient>
        <linearGradient id={id("paw")} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="1" stopColor="#e9e7f4" />
        </linearGradient>
        <linearGradient id={id("band")} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#3f73e6" />
          <stop offset="1" stopColor="#2450c2" />
        </linearGradient>
        <radialGradient id={id("iris")} cx="0.5" cy="0.85" r="0.75">
          <stop offset="0" stopColor="#4a6fc9" />
          <stop offset="1" stopColor="#1b1a33" />
        </radialGradient>
        <path id={id("band-line")} d="M35 29.5C58 27 86 37 108 53" />
      </defs>

      <g mask={url("fade")}>
        <g fill="#ffd84a" stroke="#f2a93b" strokeWidth="1.2">
          <g className="origin-center transform-fill motion-safe:animate-seal-spark">
            <rect
              x="15.7"
              y="5.2"
              width="13"
              height="6.6"
              rx="2.4"
              transform="rotate(58 22.2 8.5)"
            />
          </g>
          <g className="origin-center transform-fill motion-safe:animate-seal-spark-2">
            <rect
              x="3.6"
              y="14.6"
              width="14.7"
              height="6.6"
              rx="2.4"
              transform="rotate(35 11 17.9)"
            />
          </g>
          <g className="origin-center transform-fill motion-safe:animate-seal-spark-3">
            <rect
              x="1.5"
              y="28"
              width="12.5"
              height="6.4"
              rx="2.4"
              transform="rotate(-24 7.7 31.2)"
            />
          </g>
        </g>

        <g className="origin-[64px_128px] transform-view motion-safe:animate-seal-bob">
          <path
            fill={url("fur")}
            stroke="#2a1c1c"
            strokeWidth="2.2"
            d="M2 130V84C3 70 6 56 14 44 24 20 50 3 76 3c22 0 37 14 44 35 5 18 6 46 6 92Z"
          />

          <g fill="none" stroke="#2a1c1c" strokeWidth="1.6" strokeLinecap="round">
            <path d="M9 53.5Q15 54 21 59" />
            <path d="M5 63q7-2 15 1" />
            <path d="M6 69q6-1 11 1" />
            <path d="M102 79.5q8 .5 15 6" />
            <path d="M101.5 85q6.5 3 12 9" />
          </g>

          <ellipse cx="24.7" cy="65.7" rx="10.5" ry="8.5" fill="#f9c9c4" opacity="0.85" />
          <ellipse cx="90.4" cy="84.5" rx="10.5" ry="7.5" fill="#f9c9c4" opacity="0.85" />
          <g fill="none" stroke="#ee7b70" strokeWidth="1.1" strokeLinecap="round">
            <path d="M22 63l2.5 4.5" />
            <path d="M27 62.5l2.5 4.5" />
            <path d="M87.5 86l2.5-4.5" />
            <path d="M92.5 86.5l2.5-4.5" />
          </g>

          <g fill="none" stroke="#8e93a6" strokeWidth="1.6" strokeLinecap="round">
            <path d="M47.5 39l2.5 4" />
            <path d="M83.5 54.5l6.5-1.5" />
          </g>

          <g className="origin-[37.5px_55px] transform-view motion-safe:animate-seal-blink">
            <ellipse
              cx="37.5"
              cy="54.6"
              rx="9.6"
              ry="10.2"
              fill={url("iris")}
              transform="rotate(12 37.5 54.6)"
            />
            <circle cx="35.5" cy="50.3" r="3.2" fill="#ffffff" />
            <circle cx="36" cy="55.5" r="0.9" fill="#ffffff" />
            <circle cx="35" cy="61.5" r="1.4" fill="#ffffff" />
          </g>

          <path
            fill="none"
            stroke="#201818"
            strokeWidth="4"
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M96 66q-10 0-17 5 7 2 13 6"
          />

          <path
            fill="#efeae6"
            d="M41 67c2-5 10-8 18-8s15 4 16 13c-1 3-4 5-7.5 4.5C63 76 60 72 59 68c-1 3.5-4 5.5-7 6-5 .5-9-2.5-11-7Z"
          />
          <path
            fill="#cf4f55"
            stroke="#2a1c1c"
            strokeWidth="1.8"
            strokeLinejoin="round"
            d="M48.5 78C52 77.5 57 74 59 71c2 3 5 5 8.5 5.5C67 84 62 91.5 56 91.5c-5.5 0-8.5-7.5-7.5-13.5Z"
          />
          <g clipPath={url("mouth")}>
            <path fill="#f08c84" d="M47 87c3-5 15-7 21-3v9H47Z" />
          </g>
          <path
            fill="none"
            stroke="#2a1c1c"
            strokeWidth="2"
            strokeLinecap="round"
            d="M40.5 66.5C42 72 47 75 52 74c3-.5 6-2.5 7-6 1 4 4 8 9 8.5 3 0 5.5-1.5 7-4"
          />
          <ellipse cx="58.9" cy="64.8" rx="5.3" ry="3.2" fill="#2a1c1c" />
          <ellipse cx="57.3" cy="63.7" rx="1.3" ry="0.7" fill="#ffffff" opacity="0.85" />

          <g
            className="origin-[120px_75px] transform-view motion-safe:animate-seal-wag"
            fill="#2f5fd3"
            stroke="#14224f"
            strokeWidth="2"
            strokeLinejoin="round"
          >
            <path
              fill="#2858cb"
              d="M120 77.4C122.4 81 125.4 85.4 127.8 89.4V93.2C126.2 95.6 123.8 97.8 121 99.6 119.8 98.4 118.9 97 118.3 95.4 118.8 89.5 119.2 83.5 120 77.4Z"
            />
            <path d="M119.6 75.4C120.6 72.6 121.6 70.6 122.8 68.6 124.6 69 126.4 70 127.8 71.3V85.6C125 82 122 78.5 119.6 75.4Z" />
          </g>

          <path
            fill={url("band")}
            stroke="#14224f"
            strokeWidth="2"
            strokeLinejoin="round"
            d="M14.4 41.8C13.7 40 13.8 38.6 14.6 36.8 17.5 27 25.5 17 36 13.5 62 9 96 24 118 38.6 120 41 122 44 123.4 46.6 124.4 49 124.5 51 123.9 53 124.6 55.5 124.6 58 123.8 60.2 123.6 62.5 123.3 64 122.7 65.5 122 68.8 121 71.6 119.8 74.2 118.6 71.8 117.6 69.8 116.8 68.4 108 58.6 78 38 48 34 33 33 24 34.8 18 38.2 16.5 39.2 15.4 40.4 14.4 41.8Z"
          />
          <path
            fill="#16328a"
            opacity="0.4"
            d="M14.4 41.8C13.7 40 13.8 38.6 14.6 36.8 15.4 34 16.6 31.5 18 29.2 18 32.6 18.8 35.4 20.6 37 19.6 37.4 18.8 37.8 18 38.2 16.5 39.2 15.4 40.4 14.4 41.8Z"
          />
          <path
            fill="#16328a"
            opacity="0.35"
            d="M120.5 42C122 48 122.2 58 120.3 69L119.8 74.2C121 71.6 122 68.8 122.7 65.5 123.3 64 123.6 62.5 123.8 60.2 124.6 58 124.6 55.5 123.9 53 124.5 51 124.4 49 123.4 46.6 122.6 45 121.6 43.4 120.5 42Z"
          />
          <text fontSize="10.5" fontWeight="800" fill="#ffffff">
            <textPath href={`#${id("band-line")}`}>오늘도 해내자!</textPath>
          </text>
          <g fill="#ffffff">
            <ellipse cx="113.8" cy="53" rx="3.3" ry="2.7" />
            <circle cx="109.7" cy="50.5" r="1.1" />
            <circle cx="111.8" cy="47" r="1.1" />
            <circle cx="115.8" cy="46.8" r="1.1" />
            <circle cx="118.4" cy="50" r="1.1" />
          </g>
        </g>

        <g className="origin-[14px_95px] transform-view motion-safe:animate-seal-pump">
          <path
            fill={url("paw")}
            stroke="#2a1c1c"
            strokeWidth="2.2"
            d="M1 84C3 75 11 69 18 70c8 2 12 10 11 17-1 5-4 9-8 10-7 2-14 1-19-3-2-3-2-7-1-10Z"
          />
          <path
            fill="none"
            stroke="#2a1c1c"
            strokeWidth="1.8"
            strokeLinecap="round"
            d="M21.5 86c1.5 3 1.5 6-.5 8M11 98c4 0 8-2 10-4M26.5 91c4.5 4 6.5 8 8 13"
          />
        </g>

        <g className="origin-[98px_120px] transform-view motion-safe:animate-seal-pump-late">
          <path
            fill={url("paw")}
            stroke="#2a1c1c"
            strokeWidth="2.2"
            d="M77 102c1-8 9-12.5 19-12.5 10 .5 20 6.5 22 16.5 1 8-2 14-6 18-12 3-26 1-31-6-3-5-4.5-11-4-16Z"
          />
          <path
            fill="none"
            stroke="#2a1c1c"
            strokeWidth="1.8"
            strokeLinecap="round"
            d="M88 108c-3 3-3 7-.5 12M108 93c6 4 11 11 13 19"
          />
        </g>
      </g>
    </svg>
  );
}
