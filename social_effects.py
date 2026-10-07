"""Original OpenCV implementations of social-camera-style screen effects.

These are local filters, not imported TikTok or Instagram effect packages.
See README.md for the visual references.
"""
import cv2
import numpy as np


SOCIAL_EFFECTS = ("RGB GLITCH", "RAINBOW DISCO", "FISHEYE", "MIRROR TWINS",
                  "KALEIDOSCOPE", "DREAM GLOW", "VHS", "LIQUID RIPPLE")


def apply_social_effect(source, effect, now):
    height, width = source.shape[:2]
    if effect == 0:
        # Time-driven horizontal tearing and separate color channel offsets.
        shift = max(1, int(width * (0.012 + 0.01 * np.sin(now * 7))))
        result = source.copy()
        result[:, :, 0] = np.roll(source[:, :, 0], shift, axis=1)
        result[:, :, 2] = np.roll(source[:, :, 2], -shift, axis=1)
        rng = np.random.default_rng(int(now * 12))
        for _ in range(5):
            y = int(rng.integers(height))
            band = max(1, height // 30)
            offset = int(rng.integers(-max(2, width // 12), max(2, width // 12)))
            result[y:y + band] = np.roll(result[y:y + band], offset, axis=1)
        return result
    if effect == 1:
        hsv = cv2.cvtColor(source, cv2.COLOR_BGR2HSV)
        hue = np.arange(width, dtype=np.float32)[None, :] * 90 / max(width, 1)
        hsv[:, :, 0] = ((hsv[:, :, 0].astype(np.float32) + hue + now * 35) % 180).astype(np.uint8)
        hsv[:, :, 1] = np.maximum(hsv[:, :, 1], 150)
        return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    if effect == 3:
        # Duplicate a full, squeezed camera crop into two mirrored portraits.
        half = (width + 1) // 2
        left = cv2.resize(source, (half, height), interpolation=cv2.INTER_LINEAR)
        return np.concatenate((left, cv2.flip(left, 1)), axis=1)[:, :width].copy()
    if effect == 5:
        softened = cv2.GaussianBlur(source, (0, 0), 4)
        highlight = cv2.GaussianBlur(cv2.subtract(source, (120, 120, 120, 0)), (0, 0), 8)
        result = cv2.addWeighted(source, 0.72, softened, 0.28, 0)
        result = cv2.addWeighted(result, 1, highlight, 0.7, 0)
        return cv2.add(result, (4, 6, 16, 0))
    if effect == 6:
        result = source.astype(np.float32)
        # Desaturation, warm faded blacks, moving tape noise, and scanlines.
        gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)[:, :, None]
        result = result * 0.75 + gray * 0.18 + np.array([6, 12, 20])
        rng = np.random.default_rng(int(now * 24))
        result += rng.normal(0, 5, (height, width, 1))
        result[int(now * 10) % 3::3] *= 0.8
        result = np.clip(result, 0, 255).astype(np.uint8)
        line = int(now * 65) % height
        result[line:line + 3] = np.roll(result[line:line + 3], max(1, width // 22), axis=1)
        cv2.putText(result, "PLAY >", (8, min(25, height - 1)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (225, 235, 225), 1, cv2.LINE_AA)
        return result

    yy, xx = np.indices((height, width), dtype=np.float32)
    cx, cy = (width - 1) / 2, (height - 1) / 2
    nx, ny = (xx - cx) / max(cx, 1), (yy - cy) / max(cy, 1)
    radius = np.sqrt(nx * nx + ny * ny)
    if effect == 2:
        # Pull sampling locations toward the center to magnify faces/objects.
        scale = 0.42 + 0.58 * np.minimum(radius, 1) ** 1.8
        map_x, map_y = cx + nx * scale * max(cx, 1), cy + ny * scale * max(cy, 1)
    elif effect == 4:
        sector = np.pi / 3
        angle = np.arctan2(ny, nx) + now * 0.18
        angle = np.abs((angle + sector / 2) % sector - sector / 2)
        map_x = cx + np.cos(angle) * radius * max(cx, 1)
        map_y = cy + np.sin(angle) * radius * max(cy, 1)
    elif effect == 7:
        map_x = xx + np.sin(ny * 9 + now * 3) * width * 0.045
        map_y = yy + np.cos(nx * 8 + now * 2.5) * height * 0.045
    else:
        raise ValueError(f"Unknown social effect: {effect}")
    return cv2.remap(source, map_x.astype(np.float32), map_y.astype(np.float32),
                     cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)


class ReleaseGesture:
    """One event per sustained open -> closed hand-window gesture."""
    def __init__(self):
        self.active = None
        self.duration = 0.0
        self.armed = False

    def update(self, dt, active):
        if active != self.active:
            self.active = active
            self.duration = 0.0
        else:
            self.duration += max(0, dt)
        if active and self.duration >= 0.25:
            self.armed = True
        elif not active and self.armed and self.duration >= 0.45:
            self.armed = False
            return True
        return False


class EffectSelector:
    """Default to release gestures; optionally use timed cycling instead."""
    def __init__(self, count, selected=0, automatic=False, interval=5.0):
        if count < 1 or not 0 <= selected < count or not np.isfinite(interval) or interval <= 0:
            raise ValueError("Invalid effect selection or cycle interval")
        self.count, self.selected = count, selected
        self.automatic, self.interval = automatic, interval
        self.elapsed = 0.0
        self.gesture = ReleaseGesture()

    def update(self, dt, active):
        if not self.automatic and self.gesture.update(dt, active):
            self.selected = (self.selected + 1) % self.count
        if self.automatic and active:
            self.elapsed += max(0, dt)
            if self.elapsed >= self.interval:
                steps = int(self.elapsed / self.interval)
                self.selected = (self.selected + steps) % self.count
                self.elapsed %= self.interval
        return self.selected

    def handle_key(self, key):
        if key in (ord("a"), ord("A")):
            self.automatic = not self.automatic
            self.gesture = ReleaseGesture()
        elif key in (ord(" "), ord("n"), ord("N")):
            self.selected = (self.selected + 1) % self.count
        elif key in (ord("b"), ord("B")):
            self.selected = (self.selected - 1) % self.count
        elif ord("1") <= key <= ord("9"):
            self.selected = min(key - ord("1"), self.count - 1)
        elif key == ord("0"):
            self.selected = min(9, self.count - 1)
        else:
            return
        self.elapsed = 0.0
