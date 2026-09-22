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
