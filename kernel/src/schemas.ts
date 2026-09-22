import { createRequire } from "node:module";

/**
 * The JSON Schema files under schemas/ are the single source of truth for the
 * C35 dual-language contract. They are loaded at module init from the
 * package-local schemas/ directory so that consumers of @iterate/kernel
 * always see the same schema objects that the engine-side tests validate
 * against (never an embedded copy).
 */
const nodeRequire = createRequire(import.meta.url);

export const EVIDENCE_PACK_SCHEMA_ID =
  "https://schemas.iterate.dev/evidence-pack-0.1.json" as const;
export const DECISION_LOG_ENTRY_SCHEMA_ID =
  "https://schemas.iterate.dev/decision-log-entry-0.1-draft.json" as const;
export const RECIPE_CONFIG_SCHEMA_ID =
  "https://schemas.iterate.dev/recipe-config-0.1-draft.json" as const;

export interface JsonSchemaObject {
  readonly $id: string;
  readonly [key: string]: unknown;
}

function loadSchema(relativePath: string): JsonSchemaObject {
  return nodeRequire(relativePath) as JsonSchemaObject;
}

export const EVIDENCE_PACK_JSON_SCHEMA: JsonSchemaObject = loadSchema(
  "../schemas/evidence-pack.schema.json"
);

export const DECISION_LOG_ENTRY_JSON_SCHEMA: JsonSchemaObject = loadSchema(
  "../schemas/decision-log-entry.schema.json"
);

export const RECIPE_CONFIG_JSON_SCHEMA: JsonSchemaObject = loadSchema(
  "../schemas/recipe-config.schema.json"
);
