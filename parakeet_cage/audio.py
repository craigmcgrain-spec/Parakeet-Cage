"""Mic capture via sounddevice InputStream."""

import logging
import threading
from typing import Optional

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)


class AudioRecorder:
    """Records audio from the default (or specified) input device."""

    def __init__(self):
        self._buffer = bytearray()
        self._stream: Optional[sd.InputStream] = None
        self._lock = threading.Lock()

    def start(self, device: Optional[str] = None) -> None:
        """Open a 16-bit PCM mono 16kHz InputStream for recording."""
        with self._lock:
            if self._stream is not None:
                return
            self._buffer.clear()
            samplerate = 16000
            channels = 1
            dtype = np.int16

            def callback(indata, frames, time_info, status):
                if status:
                    logger.debug("Audio callback status: %s", status)
                self._buffer.extend(indata.tobytes())

            try:
                # Convert numeric string index if configured
                dev = int(device) if device and device.isdigit() else (device or None)
                self._stream = sd.InputStream(
                    samplerate=samplerate,
                    channels=channels,
                    dtype=dtype,
                    device=dev,
                    callback=callback,
                )
                self._stream.start()
                logger.info("Audio recording stream started on device: %s", dev or "default")
            except Exception as e:
                logger.error("Failed to start audio stream: %s", e)
                self._stream = None

    def stop(self) -> bytes:
        """Stop recording and return the accumulated PCM buffer."""
        with self._lock:
            if self._stream is None:
                return b""
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.error("Error stopping audio stream: %s", e)
            finally:
                self._stream = None

            data = bytes(self._buffer)
            self._buffer.clear()
            logger.info("Audio recording captured %d bytes", len(data))
            return data

    @property
    def is_recording(self) -> bool:
        return self._stream is not None
