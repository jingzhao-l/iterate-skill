import type { z } from "zod";
import { KernelSchemaError } from "./errors.js";
import { EvidencePackSchema, type EvidencePack } from "./evidence-pack.js";
import { DecisionLogEntrySchema, type DecisionLogEntry } from "./decision-log-entry.js";
import { RecipeConfigSchema, type RecipeConfig } from "./recipe-config.js";

function parseOrThrow<T>(schema: z.ZodType<T>, input: unknown, label: string): T {
  const result = schema.safeParse(input);
  if (result.success) {
    return result.data;
  }
  const issues = result.error.issues.map((issue) => ({
    path: issue.path.map((segment) => String(segment)).join("."),
    message: issue.message
  }));
  throw new KernelSchemaError(label, issues);
}

export function parseEvidencePack(input: unknown): EvidencePack {
  return parseOrThrow(EvidencePackSchema, input, "evidence pack");
}

export function parseDecisionLogEntry(input: unknown): DecisionLogEntry {
  return parseOrThrow(DecisionLogEntrySchema, input, "decision log entry");
}

export function parseRecipeConfig(input: unknown): RecipeConfig {
  return parseOrThrow(RecipeConfigSchema, input, "recipe config");
}
