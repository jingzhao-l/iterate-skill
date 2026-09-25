import { z } from "zod";

export const RECIPE_SCHEMA_VERSION = "glasspane.recipe/0.1-draft" as const;

export const RECIPE_NAME_MAX_LENGTH = 256;
export const RECIPE_MIN_STEPS = 1;
export const RECIPE_MAX_STEPS = 64;

export const RecipeStepKindSchema = z.enum(["act", "observe", "assert", "diagnose"]);
export type RecipeStepKind = z.infer<typeof RecipeStepKindSchema>;

export const RecipeStepSchema = z.strictObject({
  kind: RecipeStepKindSchema,
  // Two-argument `z.record`: valid on the zod 3 this package pins *and* on zod 4,
  // which made the key type mandatory. The fork of opencode runs zod 4, and its
  // typecheck caught this as `TS2554: Expected 2-3 arguments, but got 1` — a
  // latent break waiting for the day this package's zod is bumped.
  params: z.record(z.string(), z.unknown())
});
export type RecipeStep = z.infer<typeof RecipeStepSchema>;

export const RecipeConfigSchema = z.strictObject({
  schemaVersion: z.literal(RECIPE_SCHEMA_VERSION),
  name: z.string().max(RECIPE_NAME_MAX_LENGTH),
  steps: z.array(RecipeStepSchema).min(RECIPE_MIN_STEPS).max(RECIPE_MAX_STEPS)
});
export type RecipeConfig = z.infer<typeof RecipeConfigSchema>;
