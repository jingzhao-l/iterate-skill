export interface KernelSchemaIssue {
  readonly path: string;
  readonly message: string;
}

/**
 * Thrown by every parse* function in this package when the input does not
 * conform to the schema. `code` is stable and machine-readable; `issues`
 * carries one entry per violation with a JSON-path-like location.
 */
export class KernelSchemaError extends Error {
  readonly code = "KERNEL_E_SCHEMA";
  readonly issues: readonly KernelSchemaIssue[];

  constructor(label: string, issues: readonly KernelSchemaIssue[]) {
    const detail = issues
      .map((issue) => `${issue.path.length > 0 ? issue.path : "<root>"}: ${issue.message}`)
      .join("; ");
    super(`invalid ${label}: ${detail}`);
    this.name = "KernelSchemaError";
    this.issues = issues;
  }
}

/**
 * The shape of a zod error, declared structurally so `errors.ts` stays free of a
 * zod import and the module graph has no cycle: the contract functions
 * (`convergenceDecision`, `registerProvider`, `reVerificationRequestFrom`) validate
 * their own inputs and need to raise the same error `parse.ts` raises, and `parse.ts`
 * imports them.
 */
export interface SchemaErrorLike {
  readonly issues: readonly { readonly path: readonly (string | number)[]; readonly message: string }[];
}

/** One place that turns a validation failure into `KernelSchemaError`. */
export function schemaErrorFrom(label: string, error: SchemaErrorLike): KernelSchemaError {
  return new KernelSchemaError(
    label,
    error.issues.map((issue) => ({
      path: issue.path.map((segment) => String(segment)).join("."),
      message: issue.message
    }))
  );
}
