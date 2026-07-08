export interface AccessLogEntry {
  ts: string;
  tenantId: string;
  method?: string;
  path?: string;
  status: number;
  latencyMs: number;
  route?: string;
  backend?: string;
  clientIp?: string;
}

export type Logger = (entry: AccessLogEntry, signal?: AbortSignal) => Promise<void>;

export const jsonLogger: Logger = async (entry, signal) => {
  signal?.throwIfAborted();
  await new Promise(r => setImmediate(r));
  console.log(JSON.stringify(entry));
};

export function createTestLogger(out: AccessLogEntry[]): Logger {
  return async (e, signal) => {
    signal?.throwIfAborted();
    await new Promise(r => setImmediate(r));
    out.push(e);
  };
}
