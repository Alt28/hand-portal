import unittest
from types import SimpleNamespace

import cv2
import numpy as np

from hand_tracker import (MODEL, EFFECTS, PortalTracker, demo_frame, filter_image,
                          hand_polygon, render_portal)
from social_effects import EffectSelector, ReleaseGesture


class PortalTests(unittest.TestCase):
    def test_effects_preserve_outside_polygon(self):
        frame, _ = demo_frame(0, 320, 240)
        polygon = np.array([[45, 30], [280, 55], [270, 200], [60, 180]], np.float32)
        mask = np.zeros(frame.shape[:2], np.uint8)
        cv2.fillConvexPoly(mask, polygon.astype(np.int32), 255)
        for effect in range(len(EFFECTS)):
            with self.subTest(effect=effect):
                result = render_portal(frame, polygon, effect, 1, border=False)
                np.testing.assert_array_equal(result[mask == 0], frame[mask == 0])
                self.assertTrue(np.any(result[mask > 0] != frame[mask > 0]))
                self.assertEqual(result.dtype, np.uint8)

    def test_missing_or_outside_portal(self):
        frame = np.full((100, 120, 3), 40, np.uint8)
        np.testing.assert_array_equal(render_portal(frame, None, 0, 0), frame)
        outside = np.array([[-20, -20], [-10, -20], [-10, -10], [-20, -10]], np.float32)
        np.testing.assert_array_equal(render_portal(frame, outside, 0, 0), frame)
        crossing = np.array([[-20, -20], [80, -20], [80, 80], [-20, 80]], np.float32)
        result = render_portal(frame, crossing, 4, 0, border=False)
        np.testing.assert_array_equal(result[20, 20], [215, 215, 215])
        np.testing.assert_array_equal(result[90, 90], frame[90, 90])

    def test_filters_accept_small_regions(self):
        for effect in range(len(EFFECTS)):
            result = filter_image(np.zeros((1, 1, 3), np.uint8), effect, 1)
            self.assertEqual(result.shape, (1, 1, 3))

    def test_animated_effects_change_without_changing_source(self):
        frame, _ = demo_frame(0, 320, 240)
        original = frame.copy()
        for effect in (5, 6, 9, 11, 12):
            with self.subTest(effect=EFFECTS[effect]):
                before = filter_image(frame, effect, 0)
                after = filter_image(frame, effect, 1.3)
                self.assertTrue(np.any(before != after))
        np.testing.assert_array_equal(frame, original)

    def test_auto_cycle_pauses_without_hands_and_resets_on_selection(self):
        selector = EffectSelector(len(EFFECTS), selected=5, automatic=True, interval=3)
        self.assertEqual(selector.update(2, True), 5)
        self.assertEqual(selector.update(20, False), 5)
        self.assertEqual(selector.update(1, True), 6)
        selector.update(2.5, True)
        selector.handle_key(ord(' '))
        self.assertEqual(selector.update(1, True), 7)
        selector.handle_key(ord('A'))
        self.assertEqual(selector.update(30, True), 7)
        selector.handle_key(ord('1'))
        selector.handle_key(ord('b'))
        self.assertEqual(selector.selected, len(EFFECTS) - 1)
        selector.handle_key(ord('n'))
        self.assertEqual(selector.selected, 0)
        selector.handle_key(ord('0'))
        self.assertEqual(selector.selected, 9)

    def test_invalid_intervals_rejected(self):
        for interval in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                EffectSelector(len(EFFECTS), interval=interval)

    def test_release_changes_once_and_rearms_only_after_open_hold(self):
        selector = EffectSelector(len(EFFECTS), selected=len(EFFECTS) - 1)

        def hold(active, frames):
            for _ in range(frames):
                selector.update(1 / 30, active)

        hold(False, 60)  # No hands at startup must not advance.
        self.assertEqual(selector.selected, len(EFFECTS) - 1)
        hold(True, 15)
        hold(False, 5)  # Brief detection loss must not switch.
        hold(True, 15)
        self.assertEqual(selector.selected, len(EFFECTS) - 1)
        hold(False, 20)
        self.assertEqual(selector.selected, 0)
        hold(False, 300)  # Keeping hands down must not keep switching.
        self.assertEqual(selector.selected, 0)
        hold(True, 2)  # A stray detection must not rearm.
        hold(False, 30)
        self.assertEqual(selector.selected, 0)
        hold(True, 15)
        hold(False, 20)
        self.assertEqual(selector.selected, 1)

    def test_release_does_not_trigger_on_single_delayed_frame(self):
        gesture = ReleaseGesture()
        gesture.update(0, True)
        gesture.update(0.3, True)
        self.assertFalse(gesture.update(3, False))
        self.assertFalse(gesture.update(0.03, True))

    def test_auto_mode_does_not_also_advance_on_release(self):
        selector = EffectSelector(len(EFFECTS), automatic=True, interval=5)
        for active in (True, False, True, False):
            for _ in range(30):
                selector.update(1 / 30, active)
        self.assertEqual(selector.selected, 0)

    def test_tracking_reorders_corners_and_expires(self):
        tracker = PortalTracker()
        points = np.array([[10, 10], [100, 10], [100, 100], [10, 100]], np.float32)
        tracker.update(points, 1)
        result = tracker.update(np.roll(points, 2, axis=0), 1.03)
        np.testing.assert_allclose(result, points)
        self.assertIsNotNone(tracker.update(None, 1.10))
        self.assertIsNone(tracker.update(None, 1.20))
        moved = points + 40
        np.testing.assert_array_equal(tracker.update(moved, 1.21), moved)

    def test_two_open_hands_required(self):
        def hand(x):
            points = [SimpleNamespace(x=x, y=0.8) for _ in range(21)]
            points[9] = SimpleNamespace(x=x, y=0.6)
            points[4] = SimpleNamespace(x=x, y=0.7)
            points[8] = SimpleNamespace(x=x, y=0.2)
            return points
        left, right = hand(0.2), hand(0.8)
        self.assertIsNotNone(hand_polygon([left, right], 640, 480))
        self.assertIsNone(hand_polygon([left], 640, 480))
        self.assertIsNone(hand_polygon([], 640, 480))
        right[6] = SimpleNamespace(x=0.8, y=0.4)
        right[8] = SimpleNamespace(x=0.9, y=0.5)  # Bent index, thumb gap still open.
        self.assertIsNone(hand_polygon([left, right], 640, 480))
        right[8] = right[4]
        self.assertIsNone(hand_polygon([left, right], 640, 480))

    @unittest.skipUnless(MODEL.is_file(), "Download the model to run the inference smoke test")
    def test_real_model_video_inference(self):
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
        options = vision.HandLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(MODEL)),
            running_mode=vision.RunningMode.VIDEO, num_hands=2)
        with vision.HandLandmarker.create_from_options(options) as detector:
            frame = mp.Image(image_format=mp.ImageFormat.SRGB,
                             data=np.zeros((240, 320, 3), np.uint8))
            for timestamp in (0, 33, 66):
                self.assertEqual(detector.detect_for_video(frame, timestamp).hand_landmarks, [])


if __name__ == "__main__":
    unittest.main()
