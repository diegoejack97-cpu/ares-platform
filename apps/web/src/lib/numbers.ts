/** Missing amounts remain missing; never coerce null, empty text or booleans to zero. */
export function finiteNumber(value: unknown): number | null {
  if (typeof value !== "number" && typeof value !== "string") return null;
  if (typeof value === "string" && !value.trim()) return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

export function safeSum<T>(items: readonly T[], field: keyof T) {
  let total = 0;
  let missing = 0;
  for (const item of items) {
    const value = finiteNumber(item[field]);
    if (value === null || !Number.isFinite(total + value)) missing++;
    else total += value;
  }
  return {
    total,
    missing,
    valid: items.length - missing,
    partial: missing > 0,
  };
}

export function safePercent(
  value: unknown,
  denominator: unknown,
): number | null {
  const a = finiteNumber(value);
  const b = finiteNumber(denominator);
  if (a === null || b === null || b <= 0) return null;
  return finiteNumber((a / b) * 100);
}
