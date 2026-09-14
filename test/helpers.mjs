import { readFileSync } from "node:fs";

/**
 * Canonical JSON form used by the C35 dual-language roundtrip comparison:
 * object keys sorted (UTF-16 code unit order), no insignificant whitespace,
 * number formatting delegated to the host's shortest roundtrip form.
 * The engine-side XCTest suite implements the exact same rules; any
 * divergence shows up as a fixture comparison failure.
 */
export function canonical(value) {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return "[" + value.map((item) => canonical(item)).join(",") + "]";
  }
  const keys = Object.keys(value).sort();
  return "{" + keys.map((key) => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}";
}

export function readFixture(relativePath) {
  return JSON.parse(rawFixture(relativePath));
}

export function rawFixture(relativePath) {
  return readFileSync(new URL(`../fixtures/${relativePath}`, import.meta.url), "utf8");
}
