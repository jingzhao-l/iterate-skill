import { z } from "zod";

/** Crockford base32 (excludes I, L, O, U). 26 chars = 10 timestamp + 16 random. */
export const OPERATION_ID_PATTERN = /^op_[0-9A-HJKMNP-TV-Z]{26}$/;

/** ISO-8601 UTC with fixed millisecond precision, as emitted by both codecs. */
export const ISO_MILLIS_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;

/** SHA-256 truncated to the first 16 bytes, lowercase hex (tree digest format). */
export const TREE_DIGEST_PATTERN = /^[0-9a-f]{32}$/;

export const SELECTOR_MAX_LENGTH = 512;

export const EVIDENCE_SCHEMA_VERSION = "glasspane.evidence/0.1-draft" as const;

export const AttributionLevelSchema = z.enum(["soft", "strong", "weak"]);
export type AttributionLevel = z.infer<typeof AttributionLevelSchema>;

export const CircuitBreakerLevelSchema = z.number().int().min(0).max(3);
export type CircuitBreakerLevel = z.infer<typeof CircuitBreakerLevelSchema>;

export const SelectorSchema = z.strictObject({
  role: z.string().max(SELECTOR_MAX_LENGTH),
  title: z.string().max(SELECTOR_MAX_LENGTH).optional(),
  identifier: z.string().max(SELECTOR_MAX_LENGTH).optional(),
});
export type Selector = z.infer<typeof SelectorSchema>;

export const ActionSchema = z.enum([
  "press",
  "increment",
  "decrement",
  "showMenu",
  "confirm",
  "cancel",
  "pick"
]);
export type Action = z.infer<typeof ActionSchema>;

export const AssertionPropertySchema = z.enum([
  "title",
  "value",
  "role",
  "enabled",
  "focused"
]);
export type AssertionProperty = z.infer<typeof AssertionPropertySchema>;

export const StringOrBoolSchema = z.union([z.string(), z.boolean()]);
export type StringOrBool = z.infer<typeof StringOrBoolSchema>;

export const BoundsSchema = z.strictObject({
  x: z.number(),
  y: z.number(),
  width: z.number(),
  height: z.number()
});
export type Bounds = z.infer<typeof BoundsSchema>;

export const AxEventSignalSchema = z.strictObject({
  treeDigestBefore: z.string().regex(TREE_DIGEST_PATTERN),
  treeDigestAfter: z.string().regex(TREE_DIGEST_PATTERN),
  nodeCount: z.number().int().min(0),
  axChanged: z.boolean(),
  latencyMs: z.number().min(0)
});
export type AxEventSignal = z.infer<typeof AxEventSignalSchema>;

export const PixelDiffSignalSchema = z.strictObject({
  changedPixelRatio: z.number().min(0).max(1),
  bounds: z.union([BoundsSchema, z.null()]),
  windowId: z.number().int().min(0)
});
export type PixelDiffSignal = z.infer<typeof PixelDiffSignalSchema>;

export const ResponsivenessSignalSchema = z.strictObject({
  responsive: z.boolean(),
  pingMs: z.number().min(0)
});
export type ResponsivenessSignal = z.infer<typeof ResponsivenessSignalSchema>;

export const CrashSignalSchema = z.strictObject({
  processAliveBefore: z.boolean(),
  processAliveAfter: z.boolean()
});
export type CrashSignal = z.infer<typeof CrashSignalSchema>;

export const ActSignalSchema = z.strictObject({
  selector: SelectorSchema,
  action: ActionSchema,
  actConfirmed: z.boolean()
});
export type ActSignal = z.infer<typeof ActSignalSchema>;

/** P6 §3.1: Z1 handler probe signal — present iff a probe connection served
 * the act window; null stays the honest absence marker (Z5-only form). */
export const HandlerRefSchema = z.strictObject({
  file: z.string().min(1).max(512),
  line: z.number().int().min(0)
});
export type HandlerRef = z.infer<typeof HandlerRefSchema>;

export const HandlerProbeSignalSchema = z.strictObject({
  probeVersion: z.string().min(1).max(64),
  hitCount: z.number().int().min(0),
  handlers: z.array(HandlerRefSchema).max(32),
  lateCount: z.number().int().min(0)
});
export type HandlerProbeSignal = z.infer<typeof HandlerProbeSignalSchema>;

export const StateEntrySchema = z.strictObject({
  key: z.string().min(1).max(512),
  before: z.string().max(1024),
  after: z.string().max(1024)
});
export type StateEntry = z.infer<typeof StateEntrySchema>;

export const StateDiffSignalSchema = z.strictObject({
  source: z.enum(["z1-macro", "z2-mirror", "z3-kvc"]),
  changed: z.boolean(),
  entries: z.array(StateEntrySchema).max(64)
});
export type StateDiffSignal = z.infer<typeof StateDiffSignalSchema>;

export const SignalsSchema = z.strictObject({
  act: ActSignalSchema,
  axEvent: AxEventSignalSchema.optional(),
  // Z5 channel has no in-process probes: explicit null is the honest boundary;
  // P6 §3.1 opens the object alternative once a GlassPaneProbe connects.
  handlerProbe: z.union([HandlerProbeSignalSchema, z.null()]),
  stateDiff: z.union([StateDiffSignalSchema, z.null()]),
  pixelDiff: PixelDiffSignalSchema.optional(),
  responsiveness: ResponsivenessSignalSchema.optional(),
  crash: CrashSignalSchema.optional()
});
export type Signals = z.infer<typeof SignalsSchema>;

export const AttributionSchema = z.strictObject({
  level: AttributionLevelSchema,
  contaminated: z.boolean()
});
export type Attribution = z.infer<typeof AttributionSchema>;

export const CircuitBreakerSchema = z.strictObject({
  level: CircuitBreakerLevelSchema,
  reason: z.string().optional()
});
export type CircuitBreaker = z.infer<typeof CircuitBreakerSchema>;

export const AssertionSchema = z.strictObject({
  kind: z.literal("element_property"),
  selector: SelectorSchema,
  property: AssertionPropertySchema,
  expected: StringOrBoolSchema,
  actual: StringOrBoolSchema,
  passed: z.boolean()
});
export type Assertion = z.infer<typeof AssertionSchema>;

export const DiagnosisClassSchema = z.enum([
  "T0",
  "T1",
  "T2",
  "T3",
  "T4",
  "T5",
  "T6",
  "T7",
  "T8",
  "T9",
  "NO_ANOMALY",
  "INCONCLUSIVE"
]);
export type DiagnosisClass = z.infer<typeof DiagnosisClassSchema>;

export const DiagnosisReportSchema = z.strictObject({
  path: z.string(),
  anomaly: z.string(),
  evidence: z.string(),
  next: z.string()
});
export type DiagnosisReport = z.infer<typeof DiagnosisReportSchema>;

export const DiagnosisSchema = z.strictObject({
  class: DiagnosisClassSchema,
  report: DiagnosisReportSchema
});
export type Diagnosis = z.infer<typeof DiagnosisSchema>;

export const EvidencePackSchema = z.strictObject({
  schemaVersion: z.literal(EVIDENCE_SCHEMA_VERSION),
  operationId: z.string().regex(OPERATION_ID_PATTERN),
  createdAt: z.string().regex(ISO_MILLIS_PATTERN),
  attribution: AttributionSchema,
  circuitBreaker: CircuitBreakerSchema,
  signals: SignalsSchema,
  assertion: z.union([AssertionSchema, z.null()]).optional(),
  diagnosis: z.union([DiagnosisSchema, z.null()]).optional()
});
export type EvidencePack = z.infer<typeof EvidencePackSchema>;
