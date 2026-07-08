import type { Server } from "http";
import { createApp } from "../src/app";

// Boots the app on an ephemeral port, hits a route, and exits 0/1.
// A lightweight runtime check: "does the app still start and respond?"
async function main(): Promise<void> {
  const app = createApp();
  const server: Server = await new Promise((resolve) => {
    const s = app.listen(0, () => resolve(s));
  });
  const addr = server.address();
  const port = typeof addr === "object" && addr ? addr.port : 0;

  try {
    const res = await fetch(`http://127.0.0.1:${port}/health`);
    if (res.status !== 200) {
      throw new Error(`/health returned ${res.status}`);
    }
    // eslint-disable-next-line no-console
    console.log(`boot-check OK (health=${res.status})`);
  } finally {
    server.close();
  }
}

main().catch((err) => {
  // eslint-disable-next-line no-console
  console.error("boot-check FAILED:", err);
  process.exit(1);
});
