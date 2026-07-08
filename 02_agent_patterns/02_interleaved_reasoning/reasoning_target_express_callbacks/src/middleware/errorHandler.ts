import type { ErrorRequestHandler } from "express";

// Maps repository/validation errors to HTTP status codes. "not found" errors
// become 404; everything else is treated as a 400 bad request.
export const errorHandler: ErrorRequestHandler = (err, _req, res, _next) => {
  const message = err instanceof Error ? err.message : "internal error";
  const status = /not found/i.test(message) ? 404 : 400;
  res.status(status).json({ error: message });
};
