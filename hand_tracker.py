"""A webcam filter window held between two thumbs and index fingers."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys
import time
import urllib.request

import cv2
import numpy as np

from social_effects import SOCIAL_EFFECTS, EffectSelector, apply_social_effect

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "models" / "hand_landmarker.task"
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/"
             "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task")
EFFECTS = ("NEON", "PIXEL", "COMIC", "THERMAL COLOR", "INVERT") + SOCIAL_EFFECTS
WINDOW = "Hand Portal"
CYAN = (255, 235, 70)


def download_model() -> Path:
    if MODEL.is_file():
        return MODEL
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    partial = MODEL.with_suffix(".part")
    print("Downloading Google's hand tracking model (first run only)...")
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=60) as response:
            with partial.open("wb") as target:
                while chunk := response.read(1024 * 1024):
                    target.write(chunk)
        if partial.stat().st_size < 1_000_000:
            raise RuntimeError("The model download was incomplete.")
        partial.replace(MODEL)
    except Exception as exc:
        partial.unlink(missing_ok=True)
        raise RuntimeError("Could not download the model. Check your internet "
                           f"connection and try again. Details: {exc}") from exc
    return MODEL


def hand_polygon(hands, width: int, height: int):
    """Return a convex window only when both hands have open thumb/index gaps."""
    if len(hands) != 2:
        return None
    corners = []
    for hand in hands:
        points = np.array([(p.x * width, p.y * height) for p in hand], np.float32)
        palm = max(float(np.linalg.norm(points[0] - points[9])), 1.0)
        # Folding the index finger closes the window, regardless of hand rotation.
        if np.linalg.norm(points[8] - points[0]) <= 1.08 * np.linalg.norm(points[6] - points[0]):
            return None
        if np.linalg.norm(points[4] - points[8]) < max(18, palm * 0.4):
            return None
        corners.extend([points[4], points[8]])
    corners = np.array(corners, np.float32)
    corners[:, 0] = np.clip(corners[:, 0], 0, width - 1)
    corners[:, 1] = np.clip(corners[:, 1], 0, height - 1)
    hull = cv2.convexHull(corners).reshape(-1, 2)
    if len(hull) != 4 or cv2.contourArea(hull) < 900:
        return None
    return hull


class PortalTracker:
    """Time-based smoothing, including consistent corner order across detections."""
    def __init__(self):
        self.points = None
        self.last_seen = 0.0
        self.last_update = None

    def update(self, polygon, now: float):
        dt = 1 / 30 if self.last_update is None else max(0, now - self.last_update)
        self.last_update = now
        if polygon is None:
            # Brief grace period avoids flashing when a single detection is missed.
            if now - self.last_seen > 0.15:
                self.points = None
            return self.points
        if self.points is None or now - self.last_seen > 0.15:
            self.points = polygon.copy()
        else:
            candidates = [np.roll(polygon, n, axis=0) for n in range(4)]
            aligned = min(candidates, key=lambda p: np.sum((p - self.points) ** 2))
            alpha = 1 - np.exp(-dt / 0.045)
            self.points += alpha * (aligned - self.points)
        self.last_seen = now
        return self.points


def filter_image(source: np.ndarray, effect: int, now: float) -> np.ndarray:
    if not 0 <= effect < len(EFFECTS):
        raise ValueError(f"Unknown effect: {effect}")
    if effect >= 5:
        return apply_social_effect(source, effect - 5, now)
    height, width = source.shape[:2]
    if effect == 1:
        small = cv2.resize(source, (max(1, width // 14), max(1, height // 14)),
                           interpolation=cv2.INTER_AREA)
        return cv2.resize(small, (width, height), interpolation=cv2.INTER_NEAREST)
    if effect == 2:
        smooth = cv2.bilateralFilter(source, 7, 65, 65)
        poster = (smooth // 32) * 32 + 16
        gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 55, 120)
        poster[edges > 0] = (20, 15, 30)
        return poster
    if effect == 3:
        return cv2.applyColorMap(cv2.cvtColor(source, cv2.COLOR_BGR2GRAY),
                                cv2.COLORMAP_TURBO)
    if effect == 4:
        return cv2.bitwise_not(source)

    gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 45, 110)
    tint = np.empty_like(source)
    tint[:, :, 0] = gray
    tint[:, :, 1] = (gray * 0.68).astype(np.uint8)
    tint[:, :, 2] = (gray * 0.22).astype(np.uint8)
    tint = cv2.addWeighted(source, 0.15, tint, 0.8, 0)
    ink = np.zeros_like(source)
    ink[edges > 0] = CYAN
    glow = cv2.GaussianBlur(ink, (0, 0), 3)
    result = cv2.addWeighted(tint, 1, glow, 1.5, 0)
    result = cv2.addWeighted(result, 1, ink, 0.9, 0)
    phase = int(now * 25) % 6
    result[phase::6] = (result[phase::6] * 0.65).astype(np.uint8)
    scan = int(now * 90) % max(height, 1)
    result[scan:scan + 2] = cv2.add(result[scan:scan + 2], (45, 35, 8, 0))
    return result


def render_portal(frame, polygon, effect: int, now: float, border=True):
    """Process only the bounding crop; keep pixels outside the polygon intact."""
    output = frame.copy()
    if polygon is None:
        return output
    height, width = frame.shape[:2]
    points = np.rint(polygon).astype(np.int32)
    points[:, 0] = np.clip(points[:, 0], 0, width - 1)
    points[:, 1] = np.clip(points[:, 1], 0, height - 1)
    if cv2.contourArea(points) < 1:
        return output
    x, y, w, h = cv2.boundingRect(points)
    crop = frame[y:y + h, x:x + w]
    mask = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(mask, points - (x, y), 255)
    changed = filter_image(crop, effect, now)
    region = output[y:y + h, x:x + w]
    region[mask > 0] = changed[mask > 0]
    if border:
        cv2.polylines(output, [points], True, (100, 75, 30), 5, cv2.LINE_AA)
        cv2.polylines(output, [points], True, CYAN, 1, cv2.LINE_AA)
        for point in points:
            center = tuple(int(v) for v in point)
            cv2.circle(output, center, 6, CYAN, 1, cv2.LINE_AA)
            cv2.circle(output, center, 2, (255, 255, 255), -1, cv2.LINE_AA)
    return output


def hud(frame, effect, active, fps, demo, notice, automatic=False, show_menu=False):
    width = frame.shape[1]
    cv2.rectangle(frame, (0, 0), (width, 75), (24, 20, 18), -1)
    cv2.putText(frame, "HAND / PORTAL", (20, 30), cv2.FONT_HERSHEY_SIMPLEX,
                0.7, CYAN, 2, cv2.LINE_AA)
    mode = "DEMO" if demo else ("TRACKING" if active else "WAITING FOR HANDS")
    cycle = "AUTO" if automatic else "GESTURE"
    cv2.putText(frame, f"{effect + 1}/{len(EFFECTS)} {EFFECTS[effect]}  |  {cycle}  |  {mode}  |  {fps:.0f} FPS",
                (20, 57), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (210, 215, 215), 1, cv2.LINE_AA)
    bottom = frame.shape[0]
    cv2.rectangle(frame, (0, bottom - 60), (width, bottom), (24, 20, 18), -1)
    cv2.putText(frame, "SPACE next  B back  A auto  H list  S save  Q quit", (20, bottom - 35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.47, (220, 225, 225), 1, cv2.LINE_AA)
    active_hint = ("Move your hands to move and resize the portal." if automatic else
                   "Lower a hand or fold your index finger for 0.5s to change effect.")
    hint = notice or (active_hint if active else
                      "Show BOTH hands. Spread thumbs and index fingers into two L shapes.")
    if demo and not notice:
        hint = "Demo animation. Run without --demo to use your webcam."
    cv2.putText(frame, hint, (20, bottom - 13), cv2.FONT_HERSHEY_SIMPLEX,
                0.43, CYAN, 1, cv2.LINE_AA)
    if show_menu:
        # Fit the full list even on a short camera frame.
        spacing = min(24, max(10, (bottom - 165) // len(EFFECTS)))
        x = max(0, width - 245)
        cv2.rectangle(frame, (x, 85), (width, 120 + len(EFFECTS) * spacing), (24, 20, 18), -1)
        cv2.putText(frame, "EFFECTS / SPACE TO SWITCH", (x + 10, 105),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, CYAN, 1, cv2.LINE_AA)
        for index, name in enumerate(EFFECTS):
            color = CYAN if index == effect else (190, 195, 195)
            label = f"{'>' if index == effect else ' '} {index + 1:02}  {name}"
            cv2.putText(frame, label, (x + 10, 125 + index * spacing),
                        cv2.FONT_HERSHEY_SIMPLEX, min(0.42, spacing / 36), color, 1, cv2.LINE_AA)


def demo_frame(now, width=960, height=640):
    yy, xx = np.indices((height, width))
    frame = np.stack((40 + xx * 100 // width, 30 + yy * 110 // height,
                      60 + (xx + yy) * 110 // (width + height)), axis=-1).astype(np.uint8)
    for x in range(0, width, 60):
        cv2.line(frame, (x, 0), (x, height), (70, 65, 70), 1)
    for y in range(0, height, 60):
        cv2.line(frame, (0, y), (width, y), (70, 65, 70), 1)
    cv2.circle(frame, (width // 2, height // 2), 135, (60, 180, 245), -1, cv2.LINE_AA)
    cv2.putText(frame, "HELLO", (width // 2 - 110, height // 2 + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 2, (45, 30, 55), 5, cv2.LINE_AA)
    shift = 60 * np.sin(now)
    polygon = np.array([[240 + shift, 175], [705 + shift, 205],
                        [675 + shift, 455], [270 + shift, 425]], np.float32)
    return frame, polygon


def open_camera(index):
    backends = (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY) if sys.platform == "win32" else (cv2.CAP_ANY,)
    for backend in backends:
        cap = cv2.VideoCapture(index, backend)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 960)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 640)
            cap.set(cv2.CAP_PROP_FPS, 30)
            ok, frame = cap.read()
            if ok:
                return cap, frame
        cap.release()
    raise RuntimeError(f"Cannot read camera {index}. Close other camera apps, allow desktop "
                       "camera access in Windows Settings, or try --camera 1.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", type=int, default=0, help="Webcam index (default: 0)")
    parser.add_argument("--effect", type=int, choices=range(1, len(EFFECTS) + 1), default=6)
    parser.add_argument("--auto", action="store_true", help="Cycle effects while the portal is visible")
    parser.add_argument("--interval", type=float, default=5.0, help="Seconds per effect in auto mode")
    parser.add_argument("--list-effects", action="store_true", help="Print effect numbers and exit")
    parser.add_argument("--demo", action="store_true", help="Animated preview without a camera")
    parser.add_argument("--download-model", action="store_true", help="Download model and exit")
    args = parser.parse_args()
    if not np.isfinite(args.interval) or args.interval <= 0:
        parser.error("--interval must be a positive, finite number")
    if args.list_effects:
        for number, name in enumerate(EFFECTS, 1):
            print(f"{number:2}. {name}")
        return
    if args.download_model:
        print(download_model())
        return
    cap = detector = None
    try:
        if not args.demo:
            import mediapipe as mp
            from mediapipe.tasks import python
            from mediapipe.tasks.python import vision
            options = vision.HandLandmarkerOptions(
                base_options=python.BaseOptions(model_asset_path=str(download_model())),
                running_mode=vision.RunningMode.VIDEO, num_hands=2,
                min_hand_detection_confidence=0.5, min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5)
            detector = vision.HandLandmarker.create_from_options(options)
            cap, first_frame = open_camera(args.camera)
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WINDOW, 960, 640)
        tracker = PortalTracker()
        selector = EffectSelector(len(EFFECTS), args.effect - 1, args.auto, args.interval)
        show_menu = False
        start = previous = time.perf_counter()
        timestamp = -1
        fps = 30.0
        notice, notice_until = "", 0.0
        while True:
            now = time.perf_counter()
            elapsed = now - start
            if args.demo:
                frame, polygon = demo_frame(elapsed)
            else:
                if first_frame is not None:
                    frame, first_frame = first_frame, None
                else:
                    ok, frame = cap.read()
                    if not ok:
                        raise RuntimeError("The camera stopped sending frames. Reconnect it and restart.")
                frame = cv2.flip(frame, 1)
                # Bound processing cost even when a camera ignores requested resolution.
                if frame.shape[1] > 960:
                    frame = cv2.resize(frame, (960, round(frame.shape[0] * 960 / frame.shape[1])))
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                timestamp = max(timestamp + 1, int(elapsed * 1000))
                result = detector.detect_for_video(
                    mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), timestamp)
                polygon = hand_polygon(result.hand_landmarks, frame.shape[1], frame.shape[0])
            old_effect = selector.selected
            # Use raw detection for gestures, before the drawing grace period.
            effect = selector.update(now - previous, polygon is not None)
            if effect != old_effect and not selector.automatic:
                notice = f"Next: {EFFECTS[effect]}. Open both hands to show it."
                notice_until = now + 2.5
            polygon = tracker.update(polygon, now)
            output = render_portal(frame, polygon, effect, elapsed)
            fps = 0.9 * fps + 0.1 / max(now - previous, 0.001)
            previous = now
            hud(output, effect, polygon is not None, fps, args.demo,
                notice if now < notice_until else "", selector.automatic, show_menu)
            cv2.imshow(WINDOW, output)
            key = cv2.waitKey(15 if args.demo else 1) & 0xFF
            if key in (27, ord("q"), ord("Q")):
                break
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
            selector.handle_key(key)
            if key in (ord("h"), ord("H")):
                show_menu = not show_menu
            elif key in (ord("s"), ord("S")):
                folder = ROOT / "captures"
                folder.mkdir(exist_ok=True)
                path = folder / f"portal_{datetime.now():%Y%m%d_%H%M%S_%f}.png"
                if not cv2.imwrite(str(path), output):
                    raise RuntimeError(f"Could not save snapshot to {path}")
                notice, notice_until = "Snapshot saved in captures/", now + 2.5
                print(f"Saved {path}")
    finally:
        if cap is not None:
            cap.release()
        if detector is not None:
            detector.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, cv2.error) as error:
        print(f"\nHand Portal: {error}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        pass
