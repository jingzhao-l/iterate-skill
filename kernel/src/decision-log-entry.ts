import { z } from "zod";
import { ISO_MILLIS_PATTERN, OPERATION_ID_PATTERN } from "./evidence-pack.js";

export const DECISION_ENTRY_ID_PATTERN = /^dl_[0-9A-HJKMNP-TV-Z]{26}$/;

/** SHA-256 full hex (64 lowercase chars), or the empty string for the genesis entry. */
export const PREV_ENTRY_HASH_PATTERN = /^([0-9a-f]{64})?$/;

export const SUMMARY_MAX_LENGTH = 2048;

export const DecisionOutcomeSchema = z.enum(["pass", "fail", "blocked", "inconclusive"]);
export type DecisionOutcome = z.infer<typeof DecisionOutcomeSchema>;

export const DecisionLogEntrySchema = z.strictObject({
  entryId: z.string().regex(DECISION_ENTRY_ID_PATTERN),
  sequence: z.number().int().min(0),
  prevEntryHash: z.string().regex(PREV_ENTRY_HASH_PATTERN),
  operationId: z.string().regex(OPERATION_ID_PATTERN).optional(),
  summary: z.string().max(SUMMARY_MAX_LENGTH),
  outcome: DecisionOutcomeSchema,
  createdAt: z.string().regex(ISO_MILLIS_PATTERN)
});
export type DecisionLogEntry = z.infer<typeof DecisionLogEntrySchema>;
