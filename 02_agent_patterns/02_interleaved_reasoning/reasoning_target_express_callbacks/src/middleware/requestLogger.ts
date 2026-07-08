import type { RequestHandler } from "express";

// Minimal request logger. Silent during tests (NODE_ENV === "test") so the
// jest output stays clean.
export const requestLogger: RequestHandler = (req, _res, next) => {
  if (process.env.NODE_ENV !== "test") {
    // eslint-disable-next-line no-console
    console.log(`${req.method} ${req.path}`);
  }
  next();
};
