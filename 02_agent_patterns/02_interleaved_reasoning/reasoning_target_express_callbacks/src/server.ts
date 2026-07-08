import { createApp } from "./app";

const port = Number(process.env.PORT ?? 3000);

createApp().listen(port, () => {
  // eslint-disable-next-line no-console
  console.log(`reasoning-target-express-callbacks listening on port ${port}`);
});
