# AGENTS.md — Crossy Road

Context for building a browser Crossy Road clone: one self-contained `index.html`,
Three.js r160 via importmap, no build step. Serve over HTTP (`python3 -m http.server`),
not `file://` (GLB loading needs CORS). Keep everything in one file.

These are the few rules that prevent *invisible* bugs. Follow the intent; choose your own
implementation for everything else.

## Coordinate system

Forward = **negative Z** (away from the camera). W/Up decreases the row; `score = -row`.
The character mesh faces +Z, so a forward move faces `rotation.y = PI`. The camera sits
behind the player (positive Z) looking forward.

## Collision — by position, not by grid row

Check the player against every vehicle by **mesh world position**, using **both** X and Z
distance. Row-index-only checks wrongly kill the player from adjacent lanes.

## Water & logs

Water is deadly unless the player is on a log. While riding, drift with the log and
**don't** snap the player's X back to the grid; update the logical column from the drifted
position; drown if they slide off the edge or miss.

## Trains

Rail lanes flash a warning (and sound a horn) before a fast train crosses. Spawn the train
with its **rear** at the screen edge and the locomotive leading inward, or the whole train
starts off-screen and gets culled immediately.

## Assets — load the real Kenney GLBs

Three CC0 packs live under `assets/`. **List each GLB folder for the exact filenames, then
load/cache/clone the models** — use a colored box only if a specific file fails, never as
the default. Set `castShadow`/`receiveShadow` on the meshes.

- **Player** — cube-pet animals from `assets/kenney_cube-pets_1.0/Models/GLB format/`
  (e.g. `animal-fox`, `animal-cat`, `animal-panda`, `animal-pig`, `animal-koala`,
  `animal-polar`). Offer 6 as a character select.
- **Cars** — `assets/kenney_car-kit/Models/GLB format/`; scale to ~0.68 units long and
  rotate to drive along X.
- **Trains** — `assets/kenney_train-kit/Models/GLB format/`; Kenney train origins are
  off-center, so re-center each model after scaling.
