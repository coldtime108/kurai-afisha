const keyName = "kurai-subscription-key";

export function deviceKey(create = false): string | null {
  const existing = localStorage.getItem(keyName);
  if (existing && /^[a-f0-9]{64}$/.test(existing)) return existing;
  if (!create) return null;
  const value = Array.from(crypto.getRandomValues(new Uint8Array(32)), (v) =>
    v.toString(16).padStart(2, "0"),
  ).join("");
  localStorage.setItem(keyName, value);
  return value;
}
