import { z, type ZodType } from "zod";

export const platformStatusSchema = z.enum(["ready", "watch", "action_required"]);
export const manufacturingProvenanceSchema = z.enum(["reference_scenario", "live", "empty"]);
export const readinessStatusSchema = z.enum(["ready", "action_required"]);
export const stringArraySchema = z.array(z.string());
export const nullableStringSchema = z.string().nullable();
export const autonomyLevelSchema = z.enum(["L0", "L1", "L2", "L3", "L4"]);
export const overviewMetricSchema = z.object({
  label: z.string(),
  value: z.string(),
  detail: z.string(),
  status: platformStatusSchema,
});
export const stringRecordSchema = z.record(z.string(), z.string());
export const unknownRecordSchema = z.record(z.string(), z.unknown());
export const permissionDecisionSchema = z.object({
  allowed: z.boolean(),
  reason: z.string(),
});

/** Validate without transforming the response, preserving additive API fields. */
export function parseContract<T>(schema: ZodType<T>, value: unknown): T {
  schema.parse(value);
  return value as T;
}
