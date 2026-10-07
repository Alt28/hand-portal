"""Browser frontend backed by the existing Python tracking and effects engine."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from urllib.parse import urlsplit

import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from hand_tracker import EFFECTS, MODEL, ROOT, PortalTracker, demo_frame, hand_polygon, render_portal
from social_effects import EffectSelector

app = FastAPI(title="Hand Portal", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
logger = logging.getLogger("hand_portal")
MAX_FRAME_BYTES = 1_000_000


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/api/effects")
def effects():
    return {"effects": [{"id": index + 1, "name": name} for index, name in enumerate(EFFECTS)],
            "default": 6, "model_ready": MODEL.is_file()}


class FrameSession:
    """Each browser session gets its own detector, gesture state, and effect."""
    def __init__(self):
        self.detector = None
        self.selector = EffectSelector(len(EFFECTS), selected=5)
        self.tracker = PortalTracker()
        self.started = self.previous = time.perf_counter()
        self.timestamp = -1
        self.demo = False
        self.revision = 0

    def configure(self, message):
        if not isinstance(message, dict) or message.get("type") != "configure":
            raise ValueError("Expected a configure message")
        effect = message.get("effect", self.selector.selected + 1)
        automatic = message.get("automatic", self.selector.automatic)
        demo = message.get("demo", self.demo)
        revision = message.get("revision", self.revision)
        if type(effect) is not int or not 1 <= effect <= len(EFFECTS):
            raise ValueError("Invalid effect number")
        if type(automatic) is not bool or type(demo) is not bool:
            raise ValueError("Invalid mode")
        if type(revision) is not int or revision < 0:
            raise ValueError("Invalid settings revision")
        changed = demo != self.demo
        self.selector = EffectSelector(len(EFFECTS), effect - 1, automatic)
        self.demo = demo
        self.revision = revision
        if changed:
            self.tracker = PortalTracker()
        return {"type": "configured", "effect": effect, "automatic": automatic, "demo": demo,
                "revision": self.revision}

    def load_detector(self):
        if self.detector is None:
            if not MODEL.is_file():
                raise RuntimeError("Tracking model missing. Run setup.bat, then try again.")
            import mediapipe as mp
            from mediapipe.tasks import python
            from mediapipe.tasks.python import vision
            self.mp = mp
            self.detector = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
                base_options=python.BaseOptions(model_asset_path=str(MODEL)),
                running_mode=vision.RunningMode.VIDEO, num_hands=2,
                min_hand_detection_confidence=0.5, min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5))

    def process(self, data=None):
        started = time.perf_counter()
        elapsed = started - self.started
        if self.demo:
            frame, polygon = demo_frame(elapsed)
            hands = None  # Demo geometry is not a real hand detection.
        else:
            if not data or len(data) > MAX_FRAME_BYTES:
                raise ValueError("Camera frame is empty or too large")
            frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                raise ValueError("Invalid camera image")
            if frame.shape[0] * frame.shape[1] > 2_000_000:
                raise ValueError("Camera image resolution is too large")
            if max(frame.shape[:2]) > 960:
                scale = 960 / max(frame.shape[:2])
                frame = cv2.resize(frame, (round(frame.shape[1] * scale), round(frame.shape[0] * scale)))
            self.load_detector()
            self.timestamp = max(self.timestamp + 1, int(elapsed * 1000))
            result = self.detector.detect_for_video(self.mp.Image(
                image_format=self.mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)),
                self.timestamp)
            hands = len(result.hand_landmarks)
            polygon = hand_polygon(result.hand_landmarks, frame.shape[1], frame.shape[0])
        before = self.selector.selected
        selected = self.selector.update(min(started - self.previous, 0.2), polygon is not None)
        self.previous = started
        polygon = self.tracker.update(polygon, started)
        output = render_portal(frame, polygon, selected, elapsed)
        ok, encoded = cv2.imencode(".jpg", output, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise RuntimeError("Could not render the camera frame")
        status = {"type": "frame", "effect": selected + 1, "name": EFFECTS[selected],
                  "revision": self.revision,
                  "automatic": self.selector.automatic, "active": polygon is not None,
                  "hands": hands, "demo": self.demo, "changed": selected != before,
                  "processing_ms": round((time.perf_counter() - started) * 1000, 1)}
        return status, encoded.tobytes()

    def close(self):
        if self.detector is not None:
            self.detector.close()
            self.detector = None


@app.websocket("/ws")
async def camera_socket(socket: WebSocket):
    # Do not allow unrelated websites to drive the local Python engine.
    origin = urlsplit(socket.headers.get("origin", ""))
    if origin.scheme not in ("http", "https") or origin.netloc != socket.headers.get("host"):
        await socket.close(code=1008)
        return
    await socket.accept()
    session = FrameSession()
    try:
        while True:
            message = await socket.receive()
            if message["type"] == "websocket.disconnect":
                break
            try:
                if message.get("bytes") is not None:
                    result = await asyncio.to_thread(session.process, message["bytes"])
                elif message.get("text") is not None:
                    if len(message["text"]) > 4096:
                        raise ValueError("Control message is too large")
                    command = json.loads(message["text"])
                    if isinstance(command, dict) and command.get("type") == "tick" and session.demo:
                        result = await asyncio.to_thread(session.process)
                    else:
                        await socket.send_json(session.configure(command))
                        continue
                else:
                    raise ValueError("Unsupported message")
                await socket.send_json(result[0])
                await socket.send_bytes(result[1])
            except (ValueError, RuntimeError, cv2.error) as error:
                await socket.send_json({"type": "error", "message": str(error)})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Camera session failed")
        try:
            await socket.send_json({"type": "error", "message": "The camera session stopped. Please start it again."})
        except (RuntimeError, WebSocketDisconnect):
            pass
    finally:
        await asyncio.to_thread(session.close)


if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, ws_max_size=MAX_FRAME_BYTES, ws_max_queue=1)
