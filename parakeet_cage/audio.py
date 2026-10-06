"""Mic capture via sounddevice."""

import threading

import numpy as np
import sounddevice


class AudioRecorder:
    """Records audio from the default (or specified) input device."""

    def __init__(self):
        self._buffer = bytearray()
        self._stream = None
        self._lock = threading.Lock()

    def start(self, device: str) -> None:
        """Open a 16-bit PCM mono 16kHz stream for recording."""
        with self._lock:
            if self._stream is not None:
                return
            dtype = np.int16
            channels = 1
            samplerate = 16000

            def callback(indata, frames, time_info, status, *args):
                self._buffer.extend(indata.tobytes())

            self._stream = sounddevice.Stream(
                samplerate=samplerate,
                channels=channels,
                dtype=dtype,
                device=device if device else None,
                callback=callback,
            )
            self._stream.start()

    def stop(self) -> bytes:
        """Stop recording and return the accumulated PCM buffer."""
        with self._lock:
            if self._stream is None:
                return b""
            self._stream.stop()
            self._stream.close()
            self._stream = None
            data = bytes(self._buffer)
            self._buffer.clear()
            return data

    @property
    def is_recording(self) -> bool:
        return self._stream is not None
