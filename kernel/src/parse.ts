import type { z } from "zod";
import { KernelSchemaError, schemaErrorFrom } from "./errors.js";
import {
  EvidencePackReadSchema,
  EvidencePackSchema,
  type EvidencePack
} from "./evidence-pack.js";
import { DecisionLogEntrySchema, reservedPayloadKeys, type DecisionLogEntry } from "./decision-log-entry.js";
import {
  DimensionContextInputSchema,
  DimensionContextSchema,
  refuseReservedRecordedKeys,
  type DimensionContext,
  type DimensionContextInput
} from "./dimension-context.js";
import { RecipeConfigSchema, type RecipeConfig } from "./recipe-config.js";
import { RunPlanSchema, type RunPlan } from "./run-plan.js";
import {
  InvariantReportSchema,
  ReverificationRequestSchema,
  type InvariantReport,
  type ReverificationRequest
} from "./invariant-report.js";
import { RoundStateSchema, type RoundState } from "./convergence.js";
import {
  ProviderRegistrationSchema,
  type ProviderRegistration
} from "./provider-registration.js";

function parseOrThrow<T>(schema: z.ZodType<T>, input: unknown, label: string): T {
  const result = schema.safeParse(input);
  if (result.success) {
    return result.data;
  }
  throw schemaErrorFrom(label, result.error);
}

export function parseEvidencePack(input: unknown): EvidencePack {
  return parseOrThrow(EvidencePackSchema, input, "evidence pack");
}

/**
 * Reads an evidence pack produced by the engine, tolerating only the two
 * legacy shapes documented on `EvidencePackReadSchema` (pre-freeze
 * `0.1-draft` label, `pixelDiff.bounds` key omitted by the older encoder).
 * The result always matches the write-side contract, so a caller can hand it
 * to anything typed against `EvidencePack` — which also means the pre-freeze
 * label comes back as the frozen const. Only this derived value is folded: the
 * archived bytes, and the frame a consumer passes straight through, keep their
 * own label. Use `parseEvidencePack` for anything being written: it refuses
 * both legacy shapes.
 */
export function parseEvidencePackRead(input: unknown): EvidencePack {
  const result = EvidencePackReadSchema.safeParse(input);
  if (result.success) {
    return result.data;
  }
  throw schemaErrorFrom("evidence pack", result.error);
}

export function parseDecisionLogEntry(input: unknown): DecisionLogEntry {
  // The raw value, before `z.record` copies it: see `reservedPayloadKeys`.
  const reserved = reservedPayloadKeys((input as { payload?: unknown } | null)?.payload);
  if (reserved.length > 0) {
    throw new KernelSchemaError("decision log entry", [
      {
        path: "payload",
        message: `carries ${reserved.map((key) => `"${key}"`).join(", ")}, a key JavaScript reinterprets instead of storing, so it would be missing from the canonical bytes the chain hashes`
      }
    ]);
  }
  return parseOrThrow(DecisionLogEntrySchema, input, "decision log entry");
}

export function parseRecipeConfig(input: unknown): RecipeConfig {
  return parseOrThrow(RecipeConfigSchema, input, "recipe config");
}

export function parseRunPlan(input: unknown): RunPlan {
  return parseOrThrow(RunPlanSchema, input, "run plan");
}

export function parseDimensionContext(input: unknown): DimensionContext {
  return parseOrThrow(DimensionContextSchema, input, "dimension context");
}

export function parseDimensionContextInput(input: unknown): DimensionContextInput {
  // The raw value, before `z.record` copies it: a `recorded.__proto__` key would
  // be reinterpreted instead of stored and the dimension it names would drop out
  // of the totals with no refusal. Same guard `dimensionContext` applies.
  refuseReservedRecordedKeys(input);
  return parseOrThrow(DimensionContextInputSchema, input, "dimension context input");
}

export function parseInvariantReport(input: unknown): InvariantReport {
  return parseOrThrow(InvariantReportSchema, input, "invariant report");
}

export function parseReverificationRequest(input: unknown): ReverificationRequest {
  return parseOrThrow(ReverificationRequestSchema, input, "re-verification request");
}

export function parseRoundState(input: unknown): RoundState {
  return parseOrThrow(RoundStateSchema, input, "round state");
}

export function parseProviderRegistration(input: unknown): ProviderRegistration {
  return parseOrThrow(ProviderRegistrationSchema, input, "provider registration");
}
