/**
 * Canonical JSON serialization — the cross-language form used by the C35
 * dual-binding gate.
 *
 * Rules (identical to `engine/Sources/GlassPaneEngine/CanonicalJSON.swift`,
 * which is the independent Swift implementation; divergence between the two
 * shows up as a fixture mismatch, not as a silently different digest):
 *   - object keys sorted by UTF-16 code unit order;
 *   - no insignificant whitespace;
 *   - numbers in the host's shortest roundtrip form (integral values print
 *     without a fraction on both sides);
 *   - scalars quoted exactly as `JSON.stringify` does (control chars as
 *     `\u00xx`, `/` and non-ASCII left raw).
 *
 * THE FORM IS PARTIAL, AND SAYS SO. `JSON.stringify` accepts anything and
 * silently invents a token for it: `undefined`, a function and a symbol all
 * print as the bare word `undefined`, `NaN` and `Infinity` print as `null`, a
 * `Date` prints as a quoted string, a class instance prints as `{}`. Each of
 * those would be a digest over bytes that are not JSON — the ledger line no
 * reader can `JSON.parse`, two different values sharing one digest, and a
 * Swift or Python recomputation that disagrees with the bytes on disk. So a
 * value with no JSON representation is refused with a code and a remedy
 * instead of being re-imagined, which is the same rule the Python half of this
 * contract already implements (`canonical_json.py` raises
 * `CANONICAL_JSON_E_VALUE` for anything it cannot name).
 *
 * The decision log hashes this form (see `decision-log.ts`), so the digest of
 * an entry is reproducible from TypeScript, Swift, or `printf … | sha256sum`
 * given the same bytes. That property is the point: an audit chain nobody else
 * can recompute is a claim, not evidence.
 */

export const CANONICAL_JSON_CODES = {
  value: "KERNEL_E_CANONICAL_VALUE",
  depth: "KERNEL_E_CANONICAL_DEPTH"
} as const;

export type KernelCanonicalJsonCode = (typeof CANONICAL_JSON_CODES)[keyof typeof CANONICAL_JSON_CODES];

/**
 * Every failure carries `code` + `message` + `remedy`, like the rest of this package.
 */
export class KernelCanonicalJsonError extends Error {
  readonly code: KernelCanonicalJsonCode;
  readonly remedy: string;

  constructor(code: KernelCanonicalJsonCode, message: string, remedy: string) {
    super(`${code}: ${message}`);
    this.name = "KernelCanonicalJsonError";
    this.code = code;
    this.remedy = remedy;
  }
}

/**
 * Ceiling on nesting depth. The bound exists so that "too deep to canonicalise"
 * is a refusal with a remedy rather than a `RangeError` from the call stack: the
 * deepest document any contract here can carry is a `payload` inside the 8192
 * character canonical bound, and the shortest way to spend 8192 characters is
 * one key per level, which is under 4100 levels — 512 is comfortably above
 * anything the contracts describe and far below what overflows a stack.
 */
export const CANONICAL_JSON_MAX_DEPTH = 512;

/**
 * The integer range this form can print identically everywhere.
 *
 * Above it, ECMAScript renders `1e21` as `1e+21` while Python prints
 * `1000000000000000000000`: one document, two byte sequences, two digests. The
 * published schemas state this as `minimum`/`maximum` on every integer field and
 * the zod mirrors enforce it with `.int()`, so a schema-only reader and a
 * validator-based one refuse the same document.
 */
export const KERNEL_SAFE_INTEGER_MAX = Number.MAX_SAFE_INTEGER;
export const KERNEL_SAFE_INTEGER_MIN = -Number.MAX_SAFE_INTEGER;

export function canonicalJson(value: unknown): string {
  return write(value, 0);
}

function write(value: unknown, depth: number): string {
  if (depth > CANONICAL_JSON_MAX_DEPTH) {
    throw new KernelCanonicalJsonError(
      CANONICAL_JSON_CODES.depth,
      `value is nested deeper than ${CANONICAL_JSON_MAX_DEPTH} levels`,
      "flatten what is being recorded: a digest over a structure this deep cannot be recomputed by a reader that streams the form, and no contract in this package describes nesting this deep"
    );
  }
  if (value === null) return "null";
  switch (typeof value) {
    case "string":
    case "boolean":
      return JSON.stringify(value);
    case "number":
      if (!Number.isFinite(value)) {
        throw new KernelCanonicalJsonError(
          CANONICAL_JSON_CODES.value,
          `${String(value)} has no JSON representation, and JSON.stringify would print it as \`null\``,
          "record the number the measurement produced, or record the absence of one; a digest that collapses NaN, Infinity and null into the same bytes cannot tell a failed measurement from an absent one"
        );
      }
      return JSON.stringify(value);
    case "object": {
      if (Array.isArray(value)) {
        const items: string[] = [];
        for (let i = 0; i < value.length; i++) {
          if (!Object.hasOwn(value, String(i))) {
            throw new KernelCanonicalJsonError(
              CANONICAL_JSON_CODES.value,
              `array index ${i} is a hole, which JSON has no token for`,
              "fill the position with null or drop it; a sparse array would serialise to a missing element between commas, which is not JSON at all"
            );
          }
          items.push(write(value[i], depth + 1));
        }
        return "[" + items.join(",") + "]";
      }
      if (Object.getPrototypeOf(value) !== Object.prototype && Object.getPrototypeOf(value) !== null) {
        throw new KernelCanonicalJsonError(
          CANONICAL_JSON_CODES.value,
          `a ${value instanceof Date ? "Date" : "value whose prototype is not Object.prototype"} has no place in the canonical form; JSON.stringify would print it as a string or as an empty object`,
          "convert it to the fields the contract states before digesting it — a class instance's own enumerable properties are not a documented shape, so two runtimes would print two different byte sequences for it"
        );
      }
      const record = value as Record<string, unknown>;
      const keys = Object.keys(record).sort();
      return "{" + keys.map((key) => JSON.stringify(key) + ":" + write(record[key], depth + 1)).join(",") + "}";
    }
    default:
      throw new KernelCanonicalJsonError(
        CANONICAL_JSON_CODES.value,
        `cannot canonicalise ${typeName(value)}: JSON.stringify would print it as the bare word \`undefined\`, which is not JSON`,
        "undefined, functions, symbols and bigints are not values this form can name; omit the key or put the value the producer actually has"
      );
  }
}

function typeName(value: unknown): string {
  switch (typeof value) {
    case "function":
      return "a function";
    case "symbol":
      return "a symbol";
    case "bigint":
      return "a bigint";
    case "undefined":
      return "an undefined value";
    default:
      return `a ${typeof value}`;
  }
}
