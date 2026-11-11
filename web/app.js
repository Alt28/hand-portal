const $ = (id) => document.getElementById(id);
const canvas = $('output');
const context = canvas.getContext('2d');
const video = $('camera');
const capture = document.createElement('canvas');
const captureContext = capture.getContext('2d');
let effects = [], selected = 6, automatic = false;
let socket = null, stream = null, running = false, demo = false;
let generation = 0, nextTimer = null, watchdog = null, reconnectTimer = null, pending = false;
let reconnectDelay = 1000;
let lastFrame = 0, measuredFps = 0, latestImage = null;
let revision = 0;
const title = (name) => name.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase()).replace('Rgb', 'RGB').replace('Vhs', 'VHS');

function message(text, error = false) {
  $('message').textContent = text;
  $('message').classList.toggle('error', error);
}
function updateSelection() {
  for (const button of $('effects').children) button.setAttribute('aria-pressed', String(Number(button.dataset.effect) === selected));
  $('gesture-mode').setAttribute('aria-pressed', String(!automatic));
  $('auto-mode').setAttribute('aria-pressed', String(automatic));
  $('mode-readout').textContent = automatic ? 'Timer' : 'Gesture';
  $('mode-help').textContent = automatic ? 'The effect changes every 5 seconds while the hand window is open.' : 'Lower a hand or fold an index finger for half a second. Reopen to reveal the next effect.';
}
function configure() {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({type: 'configure', effect: selected, automatic, demo, revision: ++revision}));
}
function selectEffect(id) {
  selected = id;
  updateSelection();
  configure();
}
function setMode(value) {
  automatic = value;
  updateSelection();
  configure();
}
function controls(busy) {
  $('start').disabled = busy;
  $('demo').disabled = busy;
  $('stop').hidden = !busy;
}
function cleanup() {
  generation++;
  running = false;
  pending = false;
  clearTimeout(nextTimer);
  clearTimeout(watchdog);
  clearTimeout(reconnectTimer);
  reconnectDelay = 1000;
  if (socket) { socket.onclose = null; socket.onerror = null; socket.close(); socket = null; }
  if (stream) { for (const track of stream.getTracks()) track.stop(); stream = null; }
  video.srcObject = null;
  $('status').classList.remove('live');
  $('status').textContent = 'Camera off';
  $('live-label').hidden = true;
  $('hands').textContent = '—';
  $('fps').textContent = '—';
  $('snapshot').disabled = true;
  controls(false);
}
function stop() {
  cleanup();
  canvas.hidden = true;
  $('empty').hidden = false;
  $('effect-overlay').hidden = true;
  latestImage = null;
  message('Camera stopped. Start again whenever you’re ready.');
}
function fail(text) {
  stop();
  message(text, true);
}
function setWatchdog() {
  clearTimeout(watchdog);
  watchdog = setTimeout(() => fail('The processing server is not responding. Please start again.'), 60000);
}
function queueFrame(token) {
  if (!running || token !== generation) return;
  clearTimeout(nextTimer);
  nextTimer = setTimeout(() => sendFrame(token), 40);
}
async function sendFrame(token) {
  const activeSocket = socket;
  if (!running || token !== generation || pending || activeSocket?.readyState !== WebSocket.OPEN) return;
  pending = true;
  setWatchdog();
  if (demo) {
    activeSocket.send(JSON.stringify({type: 'tick'}));
    return;
  }
  if (!video.videoWidth || video.readyState < 2) {
    pending = false;
    queueFrame(token);
    return;
  }
  const ratio = Math.min(1, 800 / Math.max(video.videoWidth, video.videoHeight));
  capture.width = Math.round(video.videoWidth * ratio);
  capture.height = Math.round(video.videoHeight * ratio);
  // Send mirrored frames so tracking and the returned effect share coordinates.
  captureContext.setTransform(-1, 0, 0, 1, capture.width, 0);
  captureContext.drawImage(video, 0, 0, capture.width, capture.height);
  captureContext.resetTransform();
  const blob = await new Promise((resolve) => capture.toBlob(resolve, 'image/jpeg', 0.8));
  if (!running || token !== generation) return;
  if (!blob) { fail('Could not capture a camera frame. Please restart the camera.'); return; }
  if (activeSocket.readyState === WebSocket.OPEN) activeSocket.send(blob);
}
function statusFromFrame(data) {
  selected = data.effect;
  automatic = data.automatic;
  updateSelection();
  $('overlay-name').textContent = title(data.name);
  $('overlay-number').textContent = String(selected).padStart(2, '0');
  canvas.dataset.effect = String(selected);
  canvas.dataset.mode = automatic ? 'timer' : 'gesture';
  $('hands').textContent = data.demo ? 'Demo' : `${data.hands} / 2`;
  $('status').textContent = data.demo ? 'Demo running' : data.active ? 'Tracking hands' : 'Looking for hands';
  if (data.demo) message('Demo scene · No camera is active. Choose an effect to preview it.');
  else if (data.changed && !automatic) message(`Next up: ${title(data.name)}. Reopen your hands to reveal it.`);
  else if (data.active) message(automatic ? 'Keep the hand window open to cycle effects every 5 seconds.' : 'Lower a hand or fold your index finger for half a second to switch.');
  else message('Show both hands in L shapes. Keep your thumbs and index fingers visible.');
}
function connectSocket(token) {
  if (!running || token !== generation) return;
  const activeSocket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
  socket = activeSocket;
  activeSocket.binaryType = 'blob';
  let incomingStatus = null;
  setWatchdog();
  activeSocket.onopen = () => {
    if (token !== generation || socket !== activeSocket) return;
    reconnectDelay = 1000;
    lastFrame = 0;
    measuredFps = 0;
    configure();
    sendFrame(token);
  };
  activeSocket.onmessage = async (event) => {
    if (token !== generation || socket !== activeSocket) return;
    try {
      if (typeof event.data === 'string') {
        const data = JSON.parse(event.data);
        if (data.type === 'error') { fail(data.message); return; }
        if (data.type === 'frame') incomingStatus = data;
        return;
      }
      const frameStatus = incomingStatus;
      incomingStatus = null;
      // Old frames must not undo a control change made while Python was busy.
      if (!frameStatus || frameStatus.revision !== revision) {
        pending = false;
        clearTimeout(watchdog);
        queueFrame(token);
        return;
      }
      const bitmap = await createImageBitmap(event.data);
      if (token !== generation || socket !== activeSocket) { bitmap.close(); return; }
      if (frameStatus.revision !== revision) {
        bitmap.close();
        pending = false;
        clearTimeout(watchdog);
        queueFrame(token);
        return;
      }
      if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) { canvas.width = bitmap.width; canvas.height = bitmap.height; }
      context.drawImage(bitmap, 0, 0);
      bitmap.close();
      statusFromFrame(frameStatus);
      latestImage = event.data;
      canvas.hidden = false;
      $('empty').hidden = true;
      $('effect-overlay').hidden = false;
      $('live-label').hidden = false;
      $('live-label').textContent = demo ? 'DEMO · CAMERA OFF' : 'LIVE CAMERA';
      $('source-label').textContent = demo ? 'EFFECT PREVIEW' : 'CAMERA PREVIEW';
      $('status').classList.add('live');
      $('snapshot').disabled = false;
      const now = performance.now();
      if (lastFrame) measuredFps = measuredFps ? measuredFps * 0.7 + 300 / (now - lastFrame) : 1000 / (now - lastFrame);
      lastFrame = now;
      $('fps').textContent = measuredFps ? `${Math.round(measuredFps)} fps` : '—';
      pending = false;
      clearTimeout(watchdog);
      queueFrame(token);
    } catch { if (token === generation) fail('Could not display the processed image. Please start again.'); }
  };
  activeSocket.onerror = () => {
    if (token === generation && socket === activeSocket) message('Connection interrupted. Reconnecting…');
  };
  activeSocket.onclose = () => {
    if (token !== generation || !running || socket !== activeSocket) return;
    socket = null;
    pending = false;
    clearTimeout(watchdog);
    clearTimeout(nextTimer);
    $('status').textContent = 'Reconnecting…';
    $('status').classList.remove('live');
    message('Connection paused. Reconnecting to the processing server…');
    const delay = reconnectDelay;
    reconnectDelay = Math.min(reconnectDelay * 2, 30000);
    reconnectTimer = setTimeout(() => connectSocket(token), delay);
  };
}
async function start(useDemo) {
  cleanup();
  const token = generation;
  demo = useDemo;
  controls(true);
  $('status').textContent = demo ? 'Starting demo…' : 'Waiting for camera…';
  message(demo ? 'Preparing your preview…' : 'Allow camera access in your browser to begin.');
  try {
    if (!demo) {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('Camera access requires localhost or HTTPS. Open http://127.0.0.1:8000 on this computer.');
      const acquired = await navigator.mediaDevices.getUserMedia({video: {width: {ideal: 800}, height: {ideal: 600}, facingMode: 'user'}, audio: false});
      if (token !== generation) { acquired.getTracks().forEach((track) => track.stop()); return; }
      stream = acquired;
      video.srcObject = stream;
      for (const track of stream.getVideoTracks()) track.onended = () => { if (token === generation) fail('Camera access ended. Start the camera again when it is available.'); };
      await video.play();
      if (token !== generation) return;
    }
    running = true;
    connectSocket(token);
  } catch (error) {
    if (token !== generation) return;
    const friendly = {NotAllowedError: 'Camera permission was denied. Allow camera access for this page, then try again.', NotFoundError: 'No camera was found. Connect a webcam or choose Try demo.', NotReadableError: 'The camera is busy. Close other camera apps, then try again.'};
    fail(friendly[error.name] || error.message || 'Could not start the camera. Try again.');
  }
}

$('start').addEventListener('click', () => start(false));
$('demo').addEventListener('click', () => start(true));
$('stop').addEventListener('click', stop);
$('gesture-mode').addEventListener('click', () => setMode(false));
$('auto-mode').addEventListener('click', () => setMode(true));
$('snapshot').addEventListener('click', () => {
  if (!latestImage) return;
  const link = document.createElement('a');
  const url = URL.createObjectURL(latestImage);
  link.href = url;
  link.download = `hand-portal-${Date.now()}.jpg`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
document.addEventListener('keydown', (event) => {
  if (event.repeat || event.ctrlKey || event.metaKey || event.altKey || /INPUT|SELECT|TEXTAREA|BUTTON/.test(event.target.tagName)) return;
  if (!effects.length) return;
  if (event.code === 'Space') { event.preventDefault(); selectEffect(selected % effects.length + 1); }
  if (event.key.toLowerCase() === 'b') selectEffect((selected + effects.length - 2) % effects.length + 1);
  if (event.key.toLowerCase() === 'q' || event.key === 'Escape') stop();
});
window.addEventListener('pagehide', cleanup);

try {
  const response = await fetch('/api/effects');
  if (!response.ok) throw new Error('Server unavailable');
  const data = await response.json();
  effects = data.effects;
  selected = data.default;
  for (const effect of effects) {
    const button = document.createElement('button');
    button.className = 'effect-button';
    button.dataset.effect = effect.id;
    const number = document.createElement('span');
    number.className = 'effect-number';
    number.textContent = String(effect.id).padStart(2, '0');
    number.setAttribute('aria-hidden', 'true');
    button.append(number, document.createTextNode(title(effect.name)));
    button.addEventListener('click', () => selectEffect(effect.id));
    $('effects').append(button);
  }
  controls(false);
  updateSelection();
  message(data.model_ready ? 'Ready when you are. Start your camera or explore the demo.' : 'The tracking model is unavailable on the server. Demo mode is available now.');
} catch {
  message('Could not load studio settings. Refresh the page and try again.', true);
}
