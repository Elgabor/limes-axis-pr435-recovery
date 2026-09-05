import { cn } from "@/lib/cn";

/**
 * The Limes Axis mark from the brand kit: a vertical Signal Blue axis split by
 * a centered diamond, with six rays converging on the center — one horizontal
 * and two true-45° diagonals per side. The axis segments taper to a point
 * toward the diamond and every ray keeps a clear gap ring around it; the
 * horizontal rays reach further out than the diagonals.
 *
 * Colors are token-driven so the mark flips with the theme: the axis and
 * diamond always render in Signal Blue while the rays use `rayColor`
 * (defaulting to currentColor — navy on light, near-white on dark).
 *
 * AxisMarkGlyph renders the raw SVG group so the mark can live inside other
 * SVG scenes; AxisMark is the standalone <svg>. The diamond stays a rotated
 * <rect> — the smoke e2e asserts `.axis-mark rect` carries the signal fill.
 */

const signal = "rgb(var(--signal, 47 100 255))";

export function AxisMarkGlyph({
  cx,
  cy,
  r,
  rayColor = "currentColor",
}: {
  cx: number;
  cy: number;
  r: number; // half-height of the vertical axis
  rayColor?: string;
}) {
  const s = r / 21; // scale relative to the 42-unit reference height
  const axisHalfW = 0.85 * s;
  const axisRectInner = 7.1 * s; // where the straight bar ends
  const axisTip = 5.3 * s; // where the tapered point aims at the diamond
  const rayW = 1.6 * s;
  const hIn = 6.25 * s;
  const hOut = 18.35 * s;
  const dIn = 4.14 * s; // 45° components: inner radius 5.85, outer 14.25
  const dOut = 10.08 * s;
  const diamondSide = 5.09 * s; // half-diagonal 3.6

  return (
    <g>
      {/* vertical axis, split by the diamond, inner ends tapered */}
      <path
        d={`M${cx - axisHalfW} ${cy - r} H${cx + axisHalfW} V${cy - axisRectInner} L${cx} ${
          cy - axisTip
        } L${cx - axisHalfW} ${cy - axisRectInner} Z`}
        style={{ fill: signal }}
      />
      <path
        d={`M${cx - axisHalfW} ${cy + r} H${cx + axisHalfW} V${cy + axisRectInner} L${cx} ${
          cy + axisTip
        } L${cx - axisHalfW} ${cy + axisRectInner} Z`}
        style={{ fill: signal }}
      />
      {/* rays: horizontal + true-45° diagonals, all aimed at the center */}
      {[-1, 1].map((side) => (
        <g key={side}>
          <line
            x1={cx + side * hOut}
            y1={cy}
            x2={cx + side * hIn}
            y2={cy}
            style={{ stroke: rayColor }}
            strokeWidth={rayW}
            strokeLinecap="round"
          />
          <line
            x1={cx + side * dOut}
            y1={cy - dOut}
            x2={cx + side * dIn}
            y2={cy - dIn}
            style={{ stroke: rayColor }}
            strokeWidth={rayW}
            strokeLinecap="round"
          />
          <line
            x1={cx + side * dOut}
            y1={cy + dOut}
            x2={cx + side * dIn}
            y2={cy + dIn}
            style={{ stroke: rayColor }}
            strokeWidth={rayW}
            strokeLinecap="round"
          />
        </g>
      ))}
      {/* center diamond */}
      <rect
        x={cx - diamondSide / 2}
        y={cy - diamondSide / 2}
        width={diamondSide}
        height={diamondSide}
        rx={0.5 * s}
        style={{ fill: signal }}
        transform={`rotate(45 ${cx} ${cy})`}
      />
    </g>
  );
}

export function AxisMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 48 48"
      className={cn("axis-mark", className)}
      aria-hidden="true"
      focusable="false"
    >
      <AxisMarkGlyph cx={24} cy={24} r={21} />
    </svg>
  );
}

export default AxisMark;
