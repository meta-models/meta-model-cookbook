<!--
  Copyright (c) Meta Platforms, Inc. and affiliates.
  All rights reserved.

  This source code is licensed under the license found in the
  LICENSE file in the root directory of this source tree.
-->

# Muse robotics: voice to motion, selfie to postcard

|  |  |
|---|---|
| **Section** | [Use cases](https://dev.meta.ai/docs/cookbook#use-cases) |
| **Time to complete** | ~45 min |
| **Model** | `muse-spark-1.3`, `muse-image-1.0`, `muse-voice-transcribe-1.0`, `sam-3.1` |
| **Harness** | Standalone Python with MuJoCo and a local kiosk |
| **Prerequisites** | Python 3.12; no credentials or hardware for offline mode; optional Reachy Mini and CUPS printer |

![AI-generated demo hero showing Reachy Mini, Muse orchestration, and a Franka Panda arm](assets/muse_robotics_hero.png)

> This is the hero artwork used by the working demo. It is an AI-generated illustration, not product photography: Reachy Mini is the visitor-facing camera, microphone, speaker, and expressive robot; a full-mesh simulated Franka Panda performs the manipulation task.

A complete, visually faithful booth flow: Muse Voice transcribes the visitor, Muse Spark routes or plans, hosted SAM previews a simulated target, a full-mesh MuJoCo Panda executes deterministic skills, Reachy Mini handles camera/audio/reactions, Muse Image restyles an opt-in image, and the kiosk composes a file-first QR postcard. The code remains hardware-free by default; model-selected intents never directly control motors, retention, or printing.

## See the real demo

![The full-mesh simulated Franka Panda executes the red-block task](assets/muse_robotics_demo.gif)

[Watch or download the higher-quality MuJoCo MP4](assets/muse_robotics_demo.mp4)

The GIF and MP4 are the retimed replay used by the working kiosk. The recipe now bundles the same MuJoCo Menagerie Panda visual and collision meshes, scene composition, colored blocks, bin, lighting, and hero camera instead of a low-poly stand-in.

![The working kiosk with the generated hero, Reachy status, simulated-arm reels, and request controls](assets/connect_kiosk.png)

The cookbook kiosk uses the same generated hero and a Reachy-forward presentation while retaining the hardened loopback-only server, launch token, single-flight execution, and stale-result protection described below.

### Muse Image example without visitor imagery

| Generated demo input | Muse Image clay restyle |
|---|---|
| ![A fictional neon desktop robot generated for the demo](assets/muse_image_input.png) | ![The same fictional robot restyled as a clay figure by Muse Image](assets/muse_image_styled.png) |

These are real Muse Image outputs created during demo development. The public offline fixture uses this fictional robot rather than a real visitor face; the live path accepts an explicitly captured image and keeps the raw source in memory.

The media above contains no visitor images, recordings, transcripts, private endpoints, or event footage. See [asset provenance](assets/ASSET_PROVENANCE.md).

## Full system

![Muse Voice or kiosk input routes into robot, portrait, and postcard workflows](assets/full_demo_flow.svg)

The recipe has two runnable layers:

1. **Robot core**: Muse Spark returns a strict plan; deterministic MuJoCo code executes it and checks final block positions.
2. **Full demo**: a session state machine connects voice, local intent routing, SAM preview, Reachy reactions, Muse Image, kiosk state, and printing through narrow adapters.

| Component | Offline default | Live adapter |
|---|---|---|
| Request input | Fixture transcript or kiosk text | Muse Voice realtime WebSocket |
| Robot planning | Validated JSON fixtures | Muse Spark `muse-spark-1.3` |
| Motion | Full-mesh MuJoCo Panda | MuJoCo remains the motion authority |
| Segmentation | Deterministic color-mask preview | Hosted SAM `sam-3.1` or an injected local predictor |
| Social robot | `FakeReachy` event log | `ReachyMiniAdapter` |
| Image styling | Fictional generated robot fixture | Muse Image `muse-image-1.0` |
| Printing | JPEG written to disk | Explicit CUPS backend |

## Setup

From this directory:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On a headless Linux machine, select MuJoCo's EGL renderer:

```bash
export MUJOCO_GL=egl
```

## Run the complete demo offline

No API key or hardware is needed:

```bash
python run_full_demo.py \
  --output-dir outputs/full_demo \
  --qr-url https://github.com/meta-models/meta-model-cookbook/tree/main/03_use_cases/14_muse_robotics
```

That one command exercises:

1. a fixture voice transcript;
2. local intent routing;
3. a presentation-only target preview;
4. an offline Muse Spark plan fixture;
5. deterministic MuJoCo execution and verification;
6. a fake Reachy reaction;
7. an AI-generated fictional robot input and offline style transform; and
8. a 100 × 148 mm, 300-DPI QR postcard written to disk.

The source image and request transcript are never written by the full-demo path or returned by the kiosk state API. Outputs live in a random per-session subdirectory under the selected output directory; only files registered in the current session are served, replaced artifacts are deleted, reset deletes current artifacts, and startup removes recipe-created session directories older than 24 hours.

## Open the local kiosk

```bash
python run_full_demo.py --serve --output-dir outputs/kiosk \
  --qr-url https://github.com/meta-models/meta-model-cookbook/tree/main/03_use_cases/14_muse_robotics
```

Then open <http://127.0.0.1:8800>. The server:

- binds to loopback only and validates the `Host` and `Origin` headers;
- embeds a random launch token and requires it for state, action, reset, and output requests;
- denies framing and cross-origin resource use to prevent clickjacking;
- accepts bounded `application/json` requests and ignores request-supplied QR URLs;
- exposes no permissive CORS headers;
- serves only registered, nonsymlink output files;
- accepts one action at a time and returns HTTP 409 while busy; and
- assigns each run an ID and ignores work completed after reset.

The kiosk text field represents either a typed request or a finalized voice transcript. Local routing requires an affirmative action phrase and rejects negated camera, robot, and print requests. The two print buttons preserve separate behavior: **Print framed** omits a QR code, while **Print + QR** uses only the operator-supplied URL.

## Use the live Meta Model APIs

Create a [Model API](https://dev.meta.ai/) key:

```bash
export MODEL_API_KEY="your-model-api-key"
```

### Muse Spark planning and Muse Image styling

```bash
python run_full_demo.py \
  --live-models \
  --qr-url https://github.com/meta-models/meta-model-cookbook/tree/main/03_use_cases/14_muse_robotics
```

`planner.py` constrains Muse Spark to allowlisted skills and objects. `full_demo/muse_image.py` sends the portrait as an `input_image` content part to the Responses API and requests PNG through the `image_generation` tool. It finds the `image_generation_call` item by type, validates the returned image format and pixel count, uses `store=False`, and does not write the source portrait.

### Muse Voice transcription

Supply a mono, 16-bit PCM WAV at 16 kHz:

```bash
python run_full_demo.py \
  --live-models \
  --voice-wav request-16khz.wav \
  --qr-url https://github.com/meta-models/meta-model-cookbook/tree/main/03_use_cases/14_muse_robotics
```

`full_demo/muse_voice.py` connects to:

```text
wss://api.meta.ai/v1/asr/realtime
```

It authenticates with `Bearer $MODEL_API_KEY`, paces PCM chunks at their realtime sample rate, sends `endStream`, and accepts only a finalized cumulative transcript. The listening run is allocated before transcription begins, so reset invalidates a late transcript before routing. Muse Voice is speech-to-text; spoken replies require a separately licensed TTS engine passed to the Reachy adapter's `speech_callback`. `FallbackTranscriber` can replay one bounded utterance through the optional `FasterWhisperTranscriber`; that fallback uses a process-scoped temporary WAV which is deleted when transcription returns, and no model weights are redistributed.

## Robot planning and simulation

Run the focused robot recipe directly:

```bash
python run_demo.py --offline "put the red block in the bin"
```

Or use live Muse Spark planning:

```bash
python run_demo.py "put the red and blue blocks in the bin"
```

The plan is constrained to this shape:

```json
{
  "skill": "pick_and_place_multi",
  "args": {"objects": ["red", "blue"]},
  "narration": "I will move the red and blue blocks into the bin."
}
```

The model never writes Python, emits joint commands, or controls the simulator directly. Unknown skills, objects, duplicate objects, extra fields, and invalid narration fail before execution.

Bundled offline requests:

```text
put the red block in the bin
put the red and blue blocks in the bin
clear the table
sort the blocks by color
```

## SAM preview

SAM is deliberately outside the control loop. A mask may decorate the current camera frame, but it cannot alter a plan, target pose, or robot waypoint. If segmentation is absent or fails, verified motion can continue without the overlay.

The offline demo uses `ColorMaskSegmenter` so the entire flow is reproducible. Live mode calls the public Responses API model `sam-3.1` with a five-second timeout and retries disabled, requests one-bit masks, parses the documented special-token output with `meta_sam_parser`, and resizes its raster to the validated source geometry for display. Errors and timeouts fail open into deterministic motion. `SamPredictorSegmenter` remains available for an externally installed, publicly licensed local predictor. No private model name, endpoint, checkpoint, or entitlement is included.

## Reachy Mini

![AI-generated illustration of Reachy Mini used by the working demo](assets/reachy_mini_card.png)

Reachy is the visitor-facing part of the experience, not a hidden adapter: its camera can capture the opt-in image, its microphone can feed Muse Voice, its speaker can play an injected TTS reply, and bounded head/antenna reactions mirror kiosk phases. The illustration above is the people-free fallback card used by the working kiosk; it is not product photography.

The default `FakeReachy` records the same reaction events and supplies the fictional robot fixture. For a supervised hardware run, install the Reachy Mini SDK according to Pollen Robotics documentation, then run:

```bash
python run_full_demo.py --serve --reachy
```

The adapter uses local SDK discovery. There are no embedded addresses, passwords, or network scans. It does **not** enable motors by default. To opt into bounded head-pose reactions:

```bash
python run_full_demo.py --serve --reachy --enable-reachy-motors
```

The kiosk asks for browser-camera permission before capturing. If permission is denied, it does not silently switch cameras; the visitor must choose **Use Reachy / configured camera** to opt into the Reachy or offline-fixture source. For a fixed-duration push-to-talk-style capture from the configured Reachy microphone:

```bash
python run_full_demo.py \
  --live-models --reachy --reachy-voice-seconds 4 \
  --qr-url https://github.com/meta-models/meta-model-cookbook/tree/main/03_use_cases/14_muse_robotics
```

The default offline gate validates image format, pixel count, and minimum dimensions; it is deliberately **not** face detection. To require a separately obtained YuNet detector model, install OpenCV and pass `--yunet-model /path/to/face_detection_yunet.onnx`.

Reachy camera and live PCM paths stay in memory. The adapter starts the SDK's recording/playback media streams, retries camera warm-up reads, converts BGR frames to JPEG, records bounded microphone windows, and exposes PCM playback. On shutdown, a motion-enabled adapter returns to neutral, disables motor torque, and exits the SDK context. Reachy speech output is an injected callback, so this recipe does not redistribute TTS models or voice files.

## Postcard and Canon SELPHY

`PostcardComposer` normalizes image orientation, contains the full image without cropping, and renders a landscape 100 × 148 mm JPEG at 300 DPI. QR output requires an explicit HTTP(S) URL; the recipe never infers one from a Git remote.

The default `FilePrinter` only writes a JPEG. A physical CUPS queue is a separate, explicit action:

```bash
python run_full_demo.py \
  --serve \
  --cups-printer YOUR_CUPS_QUEUE \
  --allow-physical-print
```

No job is submitted until the kiosk receives a print action and the operator types the one-time confirmation phrase in the launch terminal. Reset remains responsive while confirmation is pending and invalidates the job before `lp`; once the bounded CUPS critical section starts, reset waits for that irreversible submission boundary. Every CUPS command has a 10-second timeout. The adapter uses argument arrays rather than a shell command, requires an enabled queue that is accepting jobs, deduplicates request IDs, and enforces a cooldown. Canon SELPHY media names, borderless options, color profiles, and drivers vary by OS and printer model; verify them with a supervised test print before an event.

![A file-first QR postcard composed from the people-free Muse Image example](assets/postcard_qr_preview.jpg)

[See the no-crop postcard image that was physically verified on the working demo's Canon SELPHY](assets/postcard_preview.jpg).

## Privacy and fixture policy

- No real faces, recordings, transcripts, IP addresses, credentials, or visitor media are included.
- `muse_image_input.png` and `muse_image_styled.png` depict a fictional generated robot, not a person.
- Raw source-image bytes are not persisted by the full-demo workflow.
- Outputs use a random session namespace. Only current registered files are downloadable, replacement removes the older file, reset removes current files, and startup removes recipe-created session directories after 24 hours.
- The optional YuNet gate requires a separately sourced and licensed model file; none is bundled.
- The optional SAM and Reachy adapters use dependency injection and lazy imports, so the default offline path needs neither model weights nor hardware.
- Physical motion and printing require explicit flags and supervised testing.

## Run an end-to-end smoke test

```bash
MUJOCO_GL=egl python run_full_demo.py \
  --output-dir /tmp/muse-robotics-smoke \
  --qr-url https://github.com/meta-models/meta-model-cookbook/tree/main/03_use_cases/14_muse_robotics
```

## Project layout

```text
14_muse_robotics/
├── planner.py, robot.py, skills.py  # strict planning and MuJoCo core
├── run_demo.py                      # focused robot entry point
├── run_full_demo.py                 # complete offline/live composition root
├── full_demo/
│   ├── models.py, ports.py          # dependency-free contracts
│   ├── router.py, session.py        # intent routing and stale-safe state machine
│   ├── muse_voice.py                # public realtime transcription contract
│   ├── muse_image.py                # public image editing contract + fixture
│   ├── sam_preview.py               # display-only segmentation port
│   ├── reachy.py                    # fake and opt-in Reachy Mini adapters
│   ├── postcard.py                  # 300-DPI composer + file/CUPS backends
│   ├── server.py                    # loopback-only stdlib kiosk server
│   └── static/index.html            # no-build kiosk UI
├── plans/                            # deterministic plan fixtures
├── assets/                           # public-safe generated media and provenance
├── panda.xml, scene.xml              # full-mesh Panda and working-demo scene
├── third_party/franka_panda/assets/  # Apache-2.0 visual/collision meshes
└── THIRD_PARTY_NOTICES.md
```

## Simulation scope

The bundled scene uses the full MuJoCo Menagerie Panda visual and collision mesh set, with the same table, blocks, bin, lighting, and hero camera used by the working demo. Deterministic inverse kinematics and scripted skills still own every waypoint and postcondition. This is a reproducible simulation example, not a collision-safe hardware controller.

## Attribution

The Panda model and mesh bundle come from [MuJoCo Menagerie at reviewed revision `367e3d9`](https://github.com/google-deepmind/mujoco_menagerie/tree/367e3d9884401dcf6f9c27fa69f118992539039f/franka_emika_panda), licensed under Apache License 2.0. This copy points its mesh directory at the vendored assets and retains the working demo's wrist camera; `scene.xml` is the demo-specific pick-and-place scene. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
