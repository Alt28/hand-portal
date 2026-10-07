import unittest

import cv2
import numpy as np

try:
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from web_app import app, FrameSession
    WEB_AVAILABLE = True
except ImportError:
    WEB_AVAILABLE = False


@unittest.skipUnless(WEB_AVAILABLE, "Install requirements-dev.txt for web tests")
class WebTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_frontend_and_effect_catalog(self):
        page = self.client.get('/')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Start camera', page.text)
        self.assertEqual(self.client.get('/static/app.js').status_code, 200)
        catalog = self.client.get('/api/effects').json()
        self.assertEqual(len(catalog['effects']), 13)
        # Only the frontend directory is public, not project files or snapshots.
        self.assertEqual(self.client.get('/static/../web_app.py').status_code, 404)
        self.assertEqual(self.client.get('/captures/example.png').status_code, 404)

    def test_websocket_demo_and_selection(self):
        with self.client.websocket_connect('/ws', headers={'origin': 'http://testserver'}) as socket:
            socket.send_json({'type': 'configure', 'demo': True, 'effect': 13, 'revision': 3})
            self.assertEqual(socket.receive_json()['type'], 'configured')
            socket.send_json({'type': 'tick'})
            status = socket.receive_json()
            self.assertEqual(status['effect'], 13)
            self.assertEqual(status['revision'], 3)
            self.assertTrue(status['demo'])
            self.assertIsNone(status['hands'])
            frame = cv2.imdecode(np.frombuffer(socket.receive_bytes(), np.uint8), cv2.IMREAD_COLOR)
            self.assertEqual(frame.shape, (640, 960, 3))

    def test_websocket_camera_frame_runs_python_detector(self):
        image = np.zeros((240, 320, 3), np.uint8)
        ok, encoded = cv2.imencode('.jpg', image)
        self.assertTrue(ok)
        with self.client.websocket_connect('/ws', headers={'origin': 'http://testserver'}) as socket:
            socket.send_bytes(encoded.tobytes())
            status = socket.receive_json()
            self.assertEqual(status['type'], 'frame')
            self.assertEqual(status['hands'], 0)
            self.assertFalse(status['active'])
            self.assertFalse(status['demo'])
            self.assertGreater(len(socket.receive_bytes()), 100)

    def test_invalid_messages_are_recoverable(self):
        with self.client.websocket_connect('/ws', headers={'origin': 'http://testserver'}) as socket:
            socket.send_bytes(b'not an image')
            self.assertEqual(socket.receive_json()['type'], 'error')
            socket.send_json({'type': 'configure', 'effect': 999})
            self.assertEqual(socket.receive_json()['type'], 'error')
            socket.send_text('null')
            self.assertEqual(socket.receive_json()['type'], 'error')
            socket.send_json({'type': 'configure', 'effect': 6, 'demo': True})
            self.assertEqual(socket.receive_json()['type'], 'configured')

    def test_other_website_origin_rejected(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/ws', headers={'origin': 'https://unrelated.example'}):
                self.fail('Cross-origin connection accepted')

    def test_session_settings_are_isolated(self):
        first, second = FrameSession(), FrameSession()
        first.configure({'type': 'configure', 'effect': 13, 'automatic': True})
        self.assertEqual(first.selector.selected, 12)
        self.assertEqual(second.selector.selected, 5)
        self.assertFalse(second.selector.automatic)


if __name__ == '__main__':
    unittest.main()
