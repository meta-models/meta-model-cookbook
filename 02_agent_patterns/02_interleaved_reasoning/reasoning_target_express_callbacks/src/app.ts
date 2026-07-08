import express, { Express } from "express";
import { usersRouter } from "./routes/users";
import { ordersRouter } from "./routes/orders";
import { healthRouter } from "./routes/health";
import { requestLogger } from "./middleware/requestLogger";
import { errorHandler } from "./middleware/errorHandler";

export function createApp(): Express {
  const app = express();
  app.use(express.json());
  app.use(requestLogger);

  app.use("/users", usersRouter);
  app.use("/orders", ordersRouter);
  app.use("/health", healthRouter);

  app.use(errorHandler);
  return app;
}

export default createApp;
