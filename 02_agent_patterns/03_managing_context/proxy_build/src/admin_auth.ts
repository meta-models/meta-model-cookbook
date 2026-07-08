import * as crypto from "node:crypto";

export type Role = "admin" | "operator" | "viewer";

export interface TokenPayload {
  sub: string;
  role: Role;
  tenantId: string;
  exp: number;
}

function b64uEncode(buf: Buffer): string {
  return buf.toString("base64").replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
}
function b64uDecode(s: string): Buffer {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4) s += "=";
  return Buffer.from(s, "base64");
}

export async function signJWT(payload: TokenPayload, secret: string, signal?: AbortSignal): Promise<string> {
  signal?.throwIfAborted();
  await new Promise(r => setImmediate(r));
  const header = b64uEncode(Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })));
  const body = b64uEncode(Buffer.from(JSON.stringify(payload)));
  const sig = crypto.createHmac("sha256", secret).update(`${header}.${body}`).digest();
  return `${header}.${body}.${b64uEncode(sig)}`;
}

export async function verifyJWT(token: string, secret: string, signal?: AbortSignal): Promise<TokenPayload | null> {
  signal?.throwIfAborted();
  await new Promise(r => setImmediate(r));
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const [h, b, s] = parts;
  const expected = crypto.createHmac("sha256", secret).update(`${h}.${b}`).digest();
  const provided = b64uDecode(s);
  if (provided.length !== expected.length || !crypto.timingSafeEqual(provided, expected)) return null;
  try {
    const payload = JSON.parse(b64uDecode(b).toString()) as TokenPayload;
    if (typeof payload.exp !== "number" || payload.exp * 1000 < Date.now()) return null;
    if (payload.role !== "admin" && payload.role !== "operator" && payload.role !== "viewer") return null;
    if (typeof payload.tenantId !== "string") return null;
    return payload;
  } catch {
    return null;
  }
}

export async function hashPassword(password: string, signal?: AbortSignal): Promise<string> {
  signal?.throwIfAborted();
  const salt = crypto.randomBytes(16);
  return new Promise((resolve, reject) => {
    const onAbort = () => reject(signal?.reason);
    signal?.addEventListener("abort", onAbort, { once: true });
    crypto.scrypt(password, salt, 32, (err, derived) => {
      signal?.removeEventListener("abort", onAbort);
      if (err) reject(err);
      else resolve(`${salt.toString("hex")}:${derived.toString("hex")}`);
    });
  });
}

export async function verifyPassword(password: string, hash: string, signal?: AbortSignal): Promise<boolean> {
  signal?.throwIfAborted();
  const [saltHex, keyHex] = hash.split(":");
  if (!saltHex || !keyHex) return false;
  const salt = Buffer.from(saltHex, "hex");
  return new Promise((resolve, reject) => {
    const onAbort = () => reject(signal?.reason);
    signal?.addEventListener("abort", onAbort, { once: true });
    crypto.scrypt(password, salt, 32, (err, derived) => {
      signal?.removeEventListener("abort", onAbort);
      if (err) return resolve(false);
      const key = Buffer.from(keyHex, "hex");
      if (key.length !== derived.length) return resolve(false);
      resolve(crypto.timingSafeEqual(key, derived));
    });
  });
}

export function roleAllows(role: Role, required: Role): boolean {
  const order: Record<Role, number> = { admin: 3, operator: 2, viewer: 1 };
  return order[role] >= order[required];
}
