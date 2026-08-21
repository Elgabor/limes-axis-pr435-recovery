
/**
 * Limes Axis brand tokens (2026-07 redesign). Single source of truth for the
 * palette outside CSS — `app/globals.css` defines the same values as channel
 * custom properties and `lib/brand-system.test.ts` cross-checks the two.
 */
export const brandTokens = {
  /** Signal Blue — the only accent color. */
  signal: "#2f64ff",
  signalChannels: "47 100 255",
  /** Midnight Navy — ink on light, world background on dark. */
  navy: "#04122e",
  navyChannels: "4 18 46",
  /** Cloud White — light theme background. */
  cloud: "#f7f8fb",
  cloudChannels: "247 248 251",
  /** Mist Gray — hairlines and borders. */
  mist: "#d9dee8",
  mistChannels: "217 222 232",
  /** Slate Gray — muted copy. */
  slate: "#6e7a94",
  slateChannels: "110 122 148",
  /** Signal tints for fills and active states (light theme). */
  tint50: "#f3f6ff",
  tint100: "#eef3ff",
  tint200: "#dce6ff",
  /** Dark theme semantic channels — a navy world, not black. */
  dark: {
    bgChannels: "4 18 46",
    surfaceChannels: "9 26 58",
    inkChannels: "237 241 248",
    lineChannels: "34 52 88",
    mutedChannels: "158 172 200",
  },
} as const;
