import type { z } from "zod";
import { KernelSchemaError } from "./errors.js";
import {
  EvidencePackReadSchema,
  EvidencePackSchema,
  type EvidencePack
} from "./evidence-pack.js";
import { DecisionLogEntrySchema, type DecisionLogEntry } from "./decision-log-entry.js";
import { RecipeConfigSchema, type RecipeConfig } from "./recipe-config.js";

function schemaError(label: string, error: z.ZodError): KernelSchemaError {
  const issues = error.issues.map((issue) => ({
    path: issue.path.map((segment) => String(segment)).join("."),
    message: issue.message
  }));
  return new KernelSchemaError(label, issues);
}

function parseOrThrow<T>(schema: z.ZodType<T>, input: unknown, label: string): T {
  const result = schema.safeParse(input);
  if (result.success) {
    return result.data;
  }
  throw schemaError(label, result.error);
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
  throw schemaError("evidence pack", result.error);
}

export function parseDecisionLogEntry(input: unknown): DecisionLogEntry {
  return parseOrThrow(DecisionLogEntrySchema, input, "decision log entry");
}

export function parseRecipeConfig(input: unknown): RecipeConfig {
  return parseOrThrow(RecipeConfigSchema, input, "recipe config");
}
