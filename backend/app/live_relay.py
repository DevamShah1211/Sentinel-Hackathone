"""
Live view relay — RTSP in, MJPEG out.

The sandbox publishes two viewing paths and only one of them is dependable. Its
HTTP tier (HLS on 443) is frequently overloaded: measured repeatedly, an
unauthenticated request for a playlist took 9-30 s or timed out outright, which
no browser player will sit through. RTSP on 8554 opens in about four seconds and
delivers frames steadily throughout.

So the operator console does not consume the sandbox's HLS at all. This module
holds one RTSP connection per camera, decodes it with the same capture layer the
ANPR worker uses, and re-serves it to browsers as `multipart/x-mixed-replace`
MJPEG — a format every browser plays in a plain `<img>` with no player library,
no manifest, and no segment fetching.

Three properties matter for a nine-tile wall:

* **One upstream connection per camera, not per viewer.** Each connected client
  gets its own copy of an RTSP stream from the gateway, so nine tiles opening
  nine connections is what overloads it. Subscribers here share a single decode.
* **Frames are dropped, never queued.** A slow client gets the newest frame, not
  a backlog. Live video is only useful if it is live.
* **Idle cameras disconnect.** A relay with no subscribers stops after a short
  grace period, so closing a tab releases the gateway connection.

HLS remains available at the existing proxy endpoint for when the sandbox's web
tier recovers; this is the path that works today.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.vision import StreamCapture, frame_is_decodable, frame_is_smeared

logger = logging.getLogger("sentinel.relay")

# Encoding is far cheaper than it first appears. Measured on this machine, a
# 1280 px frame at quality 88 encodes in 1.7 ms and a 1080p->720p resize costs
# 1.1 ms, so one core sustains several hundred frames a second. The binding
# constraint is bandwidth to the browser and the browser's own decode, not CPU —
# which is why these values are chosen per quality profile rather than set to a
# single cautious number.
#
# Profiles are (max_edge, jpeg_quality, fps). The client asks for one; the
# default suits a 2x2 wall on a local network.
QUALITY_PROFILES: dict[str, tuple[int, int, float]] = {
    # A single maximised tile: closest to source, worth the bytes.
    "high":     (1600, 88, 20.0),
    # 2x2 — the default wall. ~30 Mbit/s across four tiles.
    "balanced": (1280, 84, 15.0),
    # 3x3 and above, where nine streams share the pipe.
    "low":      (960, 76, 12.0),
}
DEFAULT_PROFILE = "balanced"

# Upstream delivers 14-23 fps, so asking for more than that yields duplicate
# frames rather than smoother video.
MAX_USEFUL_FPS = 25.0

# A relay with no subscribers shuts down after this, releasing the upstream
# connection back to the gateway.
IDLE_TIMEOUT_SECONDS = 25.0

# How long a first subscriber waits for the first frame before being told the
# camera is unavailable. Generous because the gateway can take several seconds to
# accept an RTSP connection when it is busy.
# Measured against this gateway: consecutive RTSP connects were accepted up to
# 30 s apart when several tiles opened together, so the budget has to cover a
# queued connect plus decode rather than a single camera's connect time.
FIRST_FRAME_TIMEOUT_SECONDS = 75.0

# Frames to discard after connect. Viewing tolerates a briefly imperfect frame in
# a way inference does not: the ANPR path skips 30 frames to avoid feeding
# pre-IDR mush to the detector, but a viewer would rather see the picture a
# couple of seconds sooner.
RELAY_SETTLE_FRAMES = 8


@dataclass
class _CameraRelay:
    """
    One RTSP connection, shared by every viewer of that camera.

    The relay decodes at full rate and keeps the newest frame. Each subscriber
    encodes at whatever profile it asked for, so a maximised tile can run at high
    quality while the rest of the wall stays economical — without opening a
    second connection to the gateway.
    """
    native_id: str
    url: str
    latest_frame: "np.ndarray | None" = None
    latest_at: float = 0.0
    frame_seq: int = 0
    subscribers: int = 0
    smeared_frames: int = 0
    error: str | None = None
    _thread: threading.Thread | None = None
    _stop: threading.Event = field(default_factory=threading.Event)
    _frame_ready: threading.Event = field(default_factory=threading.Event)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"relay-{self.native_id}",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        capture = StreamCapture(self.url, name=f"relay-{self.native_id}",
                                idr_settle_frames=RELAY_SETTLE_FRAMES)
        # Decode at the upstream's own rate; subscribers throttle themselves.
        min_interval = 1.0 / MAX_USEFUL_FPS
        last_emit = 0.0
        idle_since: float | None = None

        try:
            for frame, _pts_ms, _index in capture.frames():
                if self._stop.is_set():
                    break

                # Release the upstream connection once nobody is watching.
                if self.subscribers == 0:
                    idle_since = idle_since or time.monotonic()
                    if time.monotonic() - idle_since > IDLE_TIMEOUT_SECONDS:
                        logger.info("%s: no subscribers, closing relay", self.native_id)
                        break
                else:
                    idle_since = None

                now = time.monotonic()
                if now - last_emit < min_interval:
                    continue
                last_emit = now

                # The quality gate exists to keep artefact frames out of the
                # detector. For viewing, only skip a frame that is genuinely
                # unusable — and never let the gate stop the first frame from
                # ever arriving, which leaves the tile spinning indefinitely.
                if self.latest_frame is not None:
                    if not frame_is_decodable(frame):
                        continue
                    # A corrupt keyframe smears the picture into vertical streaks.
                    # Holding the last good frame is better than showing that: the
                    # stream recovers at the next keyframe, usually within seconds.
                    if frame_is_smeared(frame):
                        self.smeared_frames += 1
                        continue

                # Hand on the decoded frame; each subscriber encodes it at the
                # size and quality it asked for.
                self.latest_frame = frame
                self.latest_at = time.time()
                self.frame_seq += 1
                self.error = None
                self._frame_ready.set()
        except Exception as exc:
            logger.warning("%s: relay stopped — %s: %s", self.native_id,
                           type(exc).__name__, exc)
            self.error = f"{type(exc).__name__}"
        finally:
            capture.stop()
            self._frame_ready.set()   # release anyone waiting for a first frame
            logger.info("%s: relay ended", self.native_id)

    def wait_for_first_frame(self, timeout: float) -> bool:
        if self.latest_frame is not None:
            return True
        self._frame_ready.wait(timeout)
        return self.latest_frame is not None

    def encode(self, max_edge: int, quality: int) -> bytes | None:
        """Encode the newest frame at the requested size and quality."""
        frame = self.latest_frame
        if frame is None:
            return None
        height, width = frame.shape[:2]
        if max(height, width) > max_edge:
            scale = max_edge / max(height, width)
            frame = cv2.resize(frame, (int(width * scale), int(height * scale)),
                               interpolation=cv2.INTER_AREA)
        ok, buffer = cv2.imencode(".jpg", frame,
                                  [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        return buffer.tobytes() if ok else None


# The gateway refuses or stalls when many RTSP connections are opened at once —
# a nine-tile wall loading at once is exactly that pattern. Starts are serialised
# with a short gap so connections arrive in an orderly queue.
RELAY_START_GAP_SECONDS = 0.7


class RelayManager:
    """Owns one relay per camera and hands out frames to subscribers."""

    def __init__(self) -> None:
        self._relays: dict[str, _CameraRelay] = {}
        self._lock = threading.Lock()
        self._last_start = 0.0

    def _relay_for(self, native_id: str, url: str) -> _CameraRelay:
        needs_gap = False
        with self._lock:
            relay = self._relays.get(native_id)
            if relay is None or (relay._thread and not relay._thread.is_alive()):
                relay = _CameraRelay(native_id=native_id, url=url)
                self._relays[native_id] = relay

            if relay._thread is None or not relay._thread.is_alive():
                # Reserve this relay's slot in the start queue while holding the
                # lock, but wait outside it — sleeping under the lock would stall
                # every other tile's request behind this one.
                now = time.monotonic()
                start_at = max(now, self._last_start + RELAY_START_GAP_SECONDS)
                self._last_start = start_at
                needs_gap = start_at > now
                wait_for = start_at - now

        if needs_gap:
            time.sleep(wait_for)
        relay.start()
        return relay

    async def stream(self, native_id: str, url: str, profile: str = DEFAULT_PROFILE):
        """
        Yield an MJPEG multipart stream for one camera.

        Frames come from the shared relay rather than the gateway, so ten viewers
        of one camera still cost one upstream connection. Encoding happens per
        subscriber, so a maximised tile can run at high quality while the rest of
        the wall stays economical.
        """
        max_edge, quality, fps = QUALITY_PROFILES.get(
            profile, QUALITY_PROFILES[DEFAULT_PROFILE])
        relay = self._relay_for(native_id, url)
        relay.subscribers += 1
        boundary = b"--sentinelframe\r\n"
        frame_interval = 1.0 / fps

        try:
            ready = await asyncio.to_thread(
                relay.wait_for_first_frame, FIRST_FRAME_TIMEOUT_SECONDS
            )
            if not ready:
                logger.warning("%s: no frame within %.0fs", native_id,
                               FIRST_FRAME_TIMEOUT_SECONDS)
                return

            last_seq = -1
            while True:
                started = time.monotonic()

                # Only encode when the relay has produced a new frame; re-sending
                # the same picture wastes CPU and bandwidth.
                if relay.frame_seq != last_seq:
                    last_seq = relay.frame_seq
                    jpeg = await asyncio.to_thread(relay.encode, max_edge, quality)
                    if jpeg:
                        header = (b"Content-Type: image/jpeg\r\n"
                                  + f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
                        yield boundary + header + jpeg + b"\r\n"

                # The upstream died and no new frames are arriving.
                if relay.latest_at and time.time() - relay.latest_at > 20:
                    logger.info("%s: upstream went quiet, ending client stream",
                                native_id)
                    return

                elapsed = time.monotonic() - started
                await asyncio.sleep(max(0.0, frame_interval - elapsed))
        except (asyncio.CancelledError, GeneratorExit):
            # The browser closed the tab or navigated away — expected.
            raise
        finally:
            relay.subscribers = max(0, relay.subscribers - 1)

    def snapshot(self, native_id: str, url: str, timeout: float = 20.0,
                 profile: str = "balanced") -> bytes | None:
        """A single current frame, for a map popup or a still preview."""
        max_edge, quality, _fps = QUALITY_PROFILES.get(profile,
                                                       QUALITY_PROFILES[DEFAULT_PROFILE])
        relay = self._relay_for(native_id, url)
        relay.subscribers += 1
        try:
            if relay.wait_for_first_frame(timeout):
                return relay.encode(max_edge, quality)
            return None
        finally:
            relay.subscribers = max(0, relay.subscribers - 1)

    def status(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "native_id": relay.native_id,
                    "running": bool(relay._thread and relay._thread.is_alive()),
                    "subscribers": relay.subscribers,
                    "has_frame": relay.latest_frame is not None,
                    "last_frame_age_s": (round(time.time() - relay.latest_at, 1)
                                         if relay.latest_at else None),
                    "smeared_frames_skipped": relay.smeared_frames,
                    "error": relay.error,
                }
                for relay in self._relays.values()
            ]

    def shutdown(self) -> None:
        with self._lock:
            for relay in self._relays.values():
                relay.stop()


relay_manager = RelayManager()
