import { Router } from "express";
import * as userRepo from "../repositories/userRepository";

// Route handlers call the callback-style repository and forward errors to the
// Express error middleware via `next(err)`. Each handler is one more level of
// callback nesting on top of the repository.

export const usersRouter = Router();

usersRouter.post("/", (req, res, next) => {
  userRepo.createUser(req.body, (err, user) => {
    if (err) {
      next(err);
      return;
    }
    res.status(201).json(user);
  });
});

usersRouter.get("/", (_req, res, next) => {
  userRepo.getAllUsers((err, users) => {
    if (err) {
      next(err);
      return;
    }
    res.json(users);
  });
});

usersRouter.get("/:id", (req, res, next) => {
  userRepo.getUser(req.params.id, (err, user) => {
    if (err) {
      next(err);
      return;
    }
    res.json(user);
  });
});
