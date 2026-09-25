/**
 * @iterate/kernel — Phase A
 *
 * Shared kernel of the iterate ecosystem, temporarily hosted in the
 * GlassPane repository (5.8 R43). The JSON Schema files under schemas/ are
 * the single source of truth; the zod mirrors in src/ must stay in sync
 * with them via the shared truth fixtures (assertion C35).
 */
export {
  EVIDENCE_PACK_SCHEMA_ID,
  DECISION_LOG_ENTRY_SCHEMA_ID,
  RECIPE_CONFIG_SCHEMA_ID,
  EVIDENCE_PACK_JSON_SCHEMA,
  DECISION_LOG_ENTRY_JSON_SCHEMA,
  RECIPE_CONFIG_JSON_SCHEMA,
  type JsonSchemaObject
} from "./schemas.js";

export {
  EVIDENCE_SCHEMA_VERSION,
  OPERATION_ID_PATTERN,
  ISO_MILLIS_PATTERN,
  TREE_DIGEST_PATTERN,
  SELECTOR_MAX_LENGTH,
  AttributionLevelSchema,
  CircuitBreakerLevelSchema,
  SelectorSchema,
  ActionSchema,
  AssertionPropertySchema,
  StringOrBoolSchema,
  BoundsSchema,
  AxEventSignalSchema,
  PixelDiffSignalSchema,
  ResponsivenessSignalSchema,
  CrashSignalSchema,
  ActSignalSchema,
  HandlerRefSchema,
  HandlerProbeSignalSchema,
  StateEntrySchema,
  StateDiffSignalSchema,
  SignalsSchema,
  AttributionSchema,
  CircuitBreakerSchema,
  AssertionSchema,
  DiagnosisClassSchema,
  DiagnosisReportSchema,
  DiagnosisSchema,
  EvidencePackSchema,
  EvidencePackReadSchema,
  type AttributionLevel,
  type CircuitBreakerLevel,
  type Selector,
  type Action,
  type AssertionProperty,
  type StringOrBool,
  type Bounds,
  type AxEventSignal,
  type PixelDiffSignal,
  type ResponsivenessSignal,
  type CrashSignal,
  type ActSignal,
  type HandlerRef,
  type HandlerProbeSignal,
  type StateEntry,
  type StateDiffSignal,
  type Signals,
  type Attribution,
  type CircuitBreaker,
  type Assertion,
  type DiagnosisClass,
  type DiagnosisReport,
  type Diagnosis,
  type EvidencePack
} from "./evidence-pack.js";

export {
  DECISION_ENTRY_ID_PATTERN,
  PREV_ENTRY_HASH_PATTERN,
  SUMMARY_MAX_LENGTH,
  DecisionOutcomeSchema,
  DecisionLogEntrySchema,
  type DecisionOutcome,
  type DecisionLogEntry
} from "./decision-log-entry.js";

export {
  RECIPE_SCHEMA_VERSION,
  RECIPE_NAME_MAX_LENGTH,
  RECIPE_MIN_STEPS,
  RECIPE_MAX_STEPS,
  RecipeStepKindSchema,
  RecipeStepSchema,
  RecipeConfigSchema,
  type RecipeStepKind,
  type RecipeStep,
  type RecipeConfig
} from "./recipe-config.js";

export {
  parseEvidencePack,
  parseEvidencePackRead,
  parseDecisionLogEntry,
  parseRecipeConfig
} from "./parse.js";

export { KernelSchemaError, type KernelSchemaIssue } from "./errors.js";
