import { Router } from "express";
import * as orderRepo from "../repositories/orderRepository";
import * as notificationService from "../services/notificationService";

// Task 5 migration target (whole module): the orders feature end-to-end —
// this router plus orderRepository plus notificationService. The `/:id/ship`
// handler ties the data layer and the event emitter together, so migrating it
// cleanly means migrating everything it touches.

export const ordersRouter = Router();

ordersRouter.post("/", (req, res, next) => {
  orderRepo.createOrder(req.body, (err, order) => {
    if (err) {
      next(err);
      return;
    }
    res.status(201).json(order);
  });
});

ordersRouter.get("/user/:userId", (req, res, next) => {
  orderRepo.getOrdersForUser(req.params.userId, (err, list) => {
    if (err) {
      next(err);
      return;
    }
    res.json(list);
  });
});

ordersRouter.post("/:id/ship", (req, res, next) => {
  orderRepo.shipOrder(req.params.id, (err, order) => {
    if (err) {
      next(err);
      return;
    }
    notificationService.emitShipped(order!.id);
    res.json(order);
  });
});
