import { z } from "zod";
import { canonicalJson, KERNEL_SAFE_INTEGER_MAX, KERNEL_SAFE_INTEGER_MIN } from "./canonical-json.js";
import { DIMENSION_ID_MAX_LENGTH, DIMENSION_ID_PATTERN } from "./dimension-context.js";
import { ISO_MILLIS_PATTERN, OPERATION_ID_PATTERN } from "./evidence-pack.js";

export const DECISION_ENTRY_ID_PATTERN = /^dl_[0-9A-HJKMNP-TV-Z]{26}$/;

/** SHA-256 full hex (64 lowercase chars), or the empty string for the genesis entry. */
export const PREV_ENTRY_HASH_PATTERN = /^([0-9a-f]{64})?$/;

export const SUMMARY_MAX_LENGTH = 2048;

/**
 * What kind of decision an entry records — snake_case producer vocabulary, deliberately
 * NOT an enum here.
 *
 * WHY IT IS NOT ENUMERATED. Each ecosystem has its own set of event kinds and each is
 * the authority on its own list: the iterate loop records `round_start`, `review_result`,
 * `atomic_fix`, `architectural_fix`, `revert`, `validation`, `decision`, `report` (and the
 * plugin's history adds `round_failed`, `resume`), while the GlassPane fork records tool
 * executions. Enumerating them in this package would make the kernel the owner of two
 * vocabularies it does not maintain, and every new kind would need a kernel release —
 * the same reason there is no dimension list in `dimension-context.ts`. The kernel's job
 * is to make the field *comparable* (shape, bound, no silent free-text drift), not to
 * decide what counts as a decision.
 */
export const DECISION_KIND_PATTERN = /^[a-z][a-z0-9_]{0,31}$/;

/**
 * Upper bound on the canonical-JSON length of `payload`. The legacy logs this shape
 * replaces put an unbounded `data` object on every line; an unbounded field in a
 * hash-chained ledger is a line whose bytes — and therefore whose digest — can grow
 * without limit, so the bound is part of the contract even though JSON Schema cannot
 * state it (see the documented divergence in `schemas/decision-log-entry.schema.json`).
 */
export const PAYLOAD_MAX_CANONICAL_LENGTH = 8192;

/**
 * Payload keys the JavaScript object model reinterprets instead of storing.
 *
 * `{"__proto__": …}` is a key a JSON reader can hand this package — Python's
 * `json.loads` produces it as an own property, and a Swift decoder names it the
 * same way — but `z.record` copies values with `out[k] = value`, which invokes
 * the `Object.prototype.__proto__` accessor rather than defining the property:
 * the key silently vanishes from the entry, and so from the bytes the digest
 * covers. `prototype` and `constructor` are NOT in this list on purpose — a plain
 * `{}` has no inherited accessor by either name, so assigning them defines an own
 * property and they survive as data. Only the key that is actually lost is refused.
 *
 * Rule 3 of the transcription contract says the payload is carried in full, so the
 * honest alternatives were to preserve the key or refuse it. Refusing is what this
 * package does everywhere else with a field it cannot carry (`DecisionLogDraftSchema`
 * refuses an unknown key rather than dropping it), and it is the only one of the two
 * that does not put a key named `__proto__` back into an object another consumer
 * will merge.
 */
export const PAYLOAD_RESERVED_KEYS = ["__proto__"] as const;

/**
 * Which keys of a RAW payload value this package cannot carry as data.
 *
 * The check has to see the input before `z.record` copies it: zod 4's record
 * assigns with `out[key] = value` and, for `__proto__` specifically, does not even
 * run the key schema — the key disappears from the parsed object, so a refinement
 * placed after it can only ever see the two keys that assignment does store.
 * `buildDecisionLogEntry` and `parseDecisionLogEntry` therefore check the raw
 * value, and this module's schema keeps the refinement for the rest.
 */
export function reservedPayloadKeys(value: unknown): string[] {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return [];
  const keys = Object.keys(value as Record<string, unknown>);
  return keys.filter((key) => (PAYLOAD_RESERVED_KEYS as readonly string[]).includes(key));
}

/**
 * Paths of every integer in a raw payload value that falls outside the range every
 * runtime prints identically.
 *
 * `sequence`/`round` carry a schema-level bound, but a payload's numbers are free-form
 * data, so this is the one place the safe-integer rule can still be violated. An
 * out-of-range integer is not refused because it is "too big" — it is refused because
 * `canonicalJson` prints numbers in the host's shortest-roundtrip form, and above 2^53
 * ECMAScript and Python print two different byte sequences for the same value. A ledger
 * line carrying one would hash differently in each implementation: the producer would
 * store a digest the verifier could not recompute, surfacing later as a false
 * "corrupt / not stored in canonical form" alert on history that was never touched.
 */
export function outOfRangePayloadIntegers(value: unknown, path = ""): string[] {
  if (typeof value === "number") {
    if (Number.isInteger(value) && (value > KERNEL_SAFE_INTEGER_MAX || value < KERNEL_SAFE_INTEGER_MIN)) {
      return [path === "" ? "<root>" : path];
    }
    return [];
  }
  if (typeof value !== "object" || value === null) return [];
  const out: string[] = [];
  if (Array.isArray(value)) {
    value.forEach((item, index) => out.push(...outOfRangePayloadIntegers(item, `${path}[${index}]`)));
    return out;
  }
  for (const key of Object.keys(value as Record<string, unknown>)) {
    const child = `${path === "" ? "" : path + "."}${key}`;
    out.push(...outOfRangePayloadIntegers((value as Record<string, unknown>)[key], child));
  }
  return out;
}

/**
 * Paths of every non-integral number in a raw payload value.
 *
 * The Python half of this contract (`canonical_json.py`) refuses EVERY float with
 * `CANONICAL_JSON_E_VALUE`: its `int` branch is the only number path it has, and
 * `JSON.stringify` drops a trailing `.0` that Python's repr keeps (and renders
 * `1e-7`/`1e+21` where Python prints `1e-07`/`1000000000000000000000`), so the two
 * cannot agree on non-integral bytes. This side digests the payload into the ledger,
 * so a float payload would hash to bytes the Python verifier cannot recompute — it
 * raises before it can hash and refuses the entry outright. Refused here for the same
 * reason as the out-of-range integer: not "too precise", but "no form both readers
 * print alike".
 */
export function nonIntegralPayloadFloats(value: unknown, path = ""): string[] {
  if (typeof value === "number") {
    if (!Number.isInteger(value)) return [path === "" ? "<root>" : path];
    return [];
  }
  if (typeof value !== "object" || value === null) return [];
  const out: string[] = [];
  if (Array.isArray(value)) {
    value.forEach((item, index) => out.push(...nonIntegralPayloadFloats(item, `${path}[${index}]`)));
    return out;
  }
  for (const key of Object.keys(value as Record<string, unknown>)) {
    const child = `${path === "" ? "" : path + "."}${key}`;
    out.push(...nonIntegralPayloadFloats((value as Record<string, unknown>)[key], child));
  }
  return out;
}

export const DecisionOutcomeSchema = z.enum(["pass", "fail", "blocked", "inconclusive"]);
export type DecisionOutcome = z.infer<typeof DecisionOutcomeSchema>;

/**
 * One line of the audit chain.
 *
 * `kind`, `round`, `dimension` and `payload` are all optional so the entries the GlassPane
 * fork already wrote keep parsing and keep their recorded digests: an omitted field is
 * absent from the canonical bytes, not `null`, so widening this shape does not retroactively
 * break a chain. They exist because the ledgers this shape is meant to replace carry that
 * information, and a canonical form that cannot state "which round, what kind, which
 * dimension, against what finding" would force each ecosystem to keep its own log beside
 * the shared one — which is the divergence this entry exists to end.
 */
export const DecisionLogEntrySchema = z.strictObject({
  entryId: z.string().regex(DECISION_ENTRY_ID_PATTERN),
  sequence: z.number().int().min(0),
  prevEntryHash: z.string().regex(PREV_ENTRY_HASH_PATTERN),
  operationId: z.string().regex(OPERATION_ID_PATTERN).optional(),
  summary: z.string().max(SUMMARY_MAX_LENGTH),
  outcome: DecisionOutcomeSchema,
  createdAt: z.string().regex(ISO_MILLIS_PATTERN),
  kind: z.string().regex(DECISION_KIND_PATTERN).optional(),
  round: z.number().int().min(0).optional(),
  dimension: z.string().regex(DIMENSION_ID_PATTERN).max(DIMENSION_ID_MAX_LENGTH).optional(),
  payload: z
    .record(z.string(), z.unknown())
    .optional()
    .superRefine((value, ctx) => {
      if (value === undefined) return;
      for (const key of Object.keys(value)) {
        if ((PAYLOAD_RESERVED_KEYS as readonly string[]).includes(key)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["payload", key],
            message: `\`payload\` cannot carry the key "${key}": assigning it in JavaScript rewrites the object instead of storing a value, so the key would disappear from the canonical bytes this entry is hashed over`
          });
        }
      }
      // The canonical form is partial, and a value it cannot name has to be
      // refused here rather than at write time: `canonicalJson` would raise, but
      // by then the ledger is what carries the news.
      let canonical: string;
      try {
        canonical = canonicalJson(value);
      } catch (error) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["payload"],
          message: error instanceof Error ? error.message : "payload contains a value with no JSON representation"
        });
        return;
      }
      if (canonical.length > PAYLOAD_MAX_CANONICAL_LENGTH) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["payload"],
          message: `payload must stay within ${PAYLOAD_MAX_CANONICAL_LENGTH} characters of canonical JSON`
        });
      }
      for (const intPath of outOfRangePayloadIntegers(value)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["payload"],
          message: `\`payload.${intPath}\` carries an integer outside ±2^53−1, which ECMAScript and Python print as two different byte sequences — a digest over it could not be recomputed by every reader`
        });
      }
      for (const floatPath of nonIntegralPayloadFloats(value)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["payload"],
          message: `\`payload.${floatPath}\` carries a non-integral number, which the Python half of this contract refuses outright (\`CANONICAL_JSON_E_VALUE\`) — ECMAScript and Python cannot print the same bytes for it, so a digest over it could not be recomputed by every reader`
        });
      }
    })
});
export type DecisionLogEntry = z.infer<typeof DecisionLogEntrySchema>;

