/**
 * The console promises to show only recorded evidence, so a surface must be
 * able to say *which* of these it is showing. `useAxisQuery` keeps the last
 * good payload when a refresh fails, which is why "stale" is a distinct state
 * rather than a flavour of "unavailable": the numbers on screen are real, they
 * are just no longer current.
 */
import type { ManufacturingProvenance } from "./platform-overview";

export type AxisSource = "loading" | "api" | "tenant_not_found" | "unavailable";

export type SourceState =
  | "loading"
  | "live"
  | "reference"
  | "empty"
  | "stale"
  | "unavailable";

/**
 * Explicit opt-in for successful API contracts that do not define payload
 * provenance. A symbol cannot be confused with a value received from JSON,
 * so callers must make the absence of provenance deliberate at the callsite.
 */
export const PROVENANCE_NOT_APPLICABLE = Symbol("provenance_not_applicable");

export type SourceProvenance =
  | ManufacturingProvenance
  | typeof PROVENANCE_NOT_APPLICABLE;

/**
 * Combine transport state with the provenance declared by the payload.
 *
 * Transport failures take precedence: cached data is stale regardless of
 * whether it was live or a reference scenario, while a failed first request
 * is unavailable. Only a successful response may be described by its payload
 * provenance. Before a payload exists, callers may omit `provenance` while a
 * query is loading or unavailable. A successful provenance-less contract must
 * pass `PROVENANCE_NOT_APPLICABLE`; an accidental omission after data arrives
 * throws instead of silently relabelling the payload as live. Runtime
 * contracts for provenance-bearing manufacturing payloads reject a missing
 * field before this helper is called.
 */
export function deriveSourceState(
  source: AxisSource,
  hasData: boolean,
  provenance?: SourceProvenance,
): SourceState {
  if (source === "tenant_not_found" || source === "unavailable") {
    return hasData ? "stale" : "unavailable";
  }

  if (source === "loading") {
    return "loading";
  }

  if (provenance === undefined) {
    if (hasData) {
      throw new Error("Successful source data requires explicit provenance");
    }
    return "unavailable";
  }

  if (provenance === "reference_scenario") {
    return "reference";
  }

  if (provenance === "empty") {
    return "empty";
  }

  return "live";
}
