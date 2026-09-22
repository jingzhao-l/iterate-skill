import { z } from "zod";

export const RECIPE_SCHEMA_VERSION = "glasspane.recipe/0.1-draft" as const;

export const RECIPE_NAME_MAX_LENGTH = 256;
export const RECIPE_MIN_STEPS = 1;
export const RECIPE_MAX_STEPS = 64;

export const RecipeStepKindSchema = z.enum(["act", "observe", "assert", "diagnose"]);
export type RecipeStepKind = z.infer<typeof RecipeStepKindSchema>;

export const RecipeStepSchema = z.strictObject({
  kind: RecipeStepKindSchema,
  params: z.record(z.unknown())
});
export type RecipeStep = z.infer<typeof RecipeStepSchema>;

export const RecipeConfigSchema = z.strictObject({
  schemaVersion: z.literal(RECIPE_SCHEMA_VERSION),
  name: z.string().max(RECIPE_NAME_MAX_LENGTH),
  steps: z.array(RecipeStepSchema).min(RECIPE_MIN_STEPS).max(RECIPE_MAX_STEPS)
});
export type RecipeConfig = z.infer<typeof RecipeConfigSchema>;
