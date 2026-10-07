# Hand Portal

A Python webcam effect inspired by your reference: both thumbs and index fingers
hold the four corners of a moving filter window. Includes 13 switchable effects;
the default is animated RGB glitch. All effects stay inside the hand window.

![Preview of eight social-style effects using a synthetic demo scene](preview/social-effects.jpg)

## Run on Windows

Double-click **setup.bat** once (internet required for dependencies and the model),
then double-click **run.bat**. Setup creates a local `.venv`; it does not install
packages into your global Python environment. Requires 64-bit Python 3.10 or newer.

Hold both hands in front of the webcam. Form an L with each thumb and index finger,
with the thumbs pointing toward one another. Separate your hands to frame an area.
Move them to resize or tilt the effect. Keep all four fingertips visible and avoid
crossing your hands. **To change effects, lower either hand, fold an index finger,
or close a thumb/index gap for about half a second. Reopen the hand window to see
the next effect.** Hold the open window briefly (at least a quarter second) before
each switch. Holding your hands down advances only once. Brief detection dropouts
are ignored; a sustained tracking loss also counts as closing the hand window.
Bright, even lighting and a clear view of both hands help tracking.

Click the video window so it receives keyboard input:

| Key | Action |
| --- | --- |
| 1 | Neon hologram |
| 2 | Retro pixelation |
| 3 | Comic posterization |
| 4 | Thermal-style colors (visual filter, not temperature measurement) |
| 5 | Inverted colors, like the reference |
| 6 | Animated RGB glitch / color split |
| 7 | Animated rainbow disco |
| 8 | Fisheye magnification |
| 9 | Mirror twins |
| 0 | Rotating kaleidoscope (effect 10) |
| Space / N | Next effect, including 11 Dream Glow, 12 VHS, 13 Liquid Ripple |
| B | Previous effect |
| A | Switch between gesture control (default) and timed cycling |
| H | Show / hide the full effect list |
| S | Save a screenshot in `captures/` |
| Q / Esc | Exit |

Open PowerShell in the downloaded or cloned project folder:

```powershell
.\run.bat
```

The default is gesture control: lower a hand or close your fingers to advance.
You can keep an effect by keeping the hand window open. Keyboard selection also works.
Optional timed mode (`.\run.bat --auto`) advances every 5 seconds while the hand
window is visible and disables gesture switching. Press A to return to gestures.
For a faster timed cycle, use `.\run.bat --auto --interval 3`.
For an animated preview without a webcam, run `.\run.bat --demo --auto`.
For a different webcam, run `run.bat --camera 1`. Start on a specific filter with
`run.bat --effect 13`. Print the numbered list with `.\run.bat --list-effects`.
You can also run `.venv\Scripts\python.exe hand_tracker.py`.

## Effect references

These are original OpenCV implementations inspired by social camera effects,
not downloaded Instagram/TikTok effect packages or an integration with either app.
Visual references from TikTok's official Effect House documentation:

- [Chromatic Aberration](https://effecthouse.tiktok.com/learn/guides/workspace/components/post-effect/post-process/chromatic-aberration): color separation, used as inspiration for RGB Glitch.
- [Disco Party](https://effecthouse.tiktok.com/learn/guides/tutorials/template-tutorials/disco-party): rainbow party styling. Our Rainbow Disco animates on a timer; it does not use audio or person segmentation.
- [Post-process filter stack](https://effecthouse.tiktok.com/learn/guides/tutorials/apjs-api/post-process-filter-stack): bloom, distortion, and grain references for Dream Glow, Fisheye, and VHS.

Fisheye and Mirror Twins transform everything inside the window. They do not
detect individual facial features or add face-attached makeup/accessories.

If the camera will not open, close other apps using it and check Windows Settings
> Privacy & security > Camera > Let desktop apps access your camera. The app tries
multiple camera backends and reports a failure if it cannot read a frame.

Camera images are processed locally. The app itself does not upload video or record
it; snapshots are saved only when S is pressed. The trained model is downloaded
from Google on first setup and reused from `models/hand_landmarker.task`.

## How it works

Uses the [MediaPipe Hand Landmarker Tasks API](https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker/python)
to locate fingertips. A convex polygon connects the four points, with time-based
smoothing to reduce jitter. OpenCV applies the chosen effect within the polygon.
The visible border and controls are drawn on top of the camera view.

The camera loop and detection are synchronous for simplicity. Actual frame rate
depends on your camera, CPU, lighting, and effect. `--demo` simulates the portal
geometry and does not test real hand detection.

Run automated geometry, masking, and model smoke checks with:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```
