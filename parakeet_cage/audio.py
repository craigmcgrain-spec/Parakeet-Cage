"""Mic capture via sounddevice InputStream with automatic hardware sample rate negotiation and resampling."""

import logging
import threading
from typing import Optional

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 16000


def resample_to_16k(pcm_bytes: bytes, src_samplerate: int) -> bytes:
    """Resample 16-bit mono PCM bytes to 16kHz using numpy interpolation."""
    if not pcm_bytes or src_samplerate == TARGET_SAMPLE_RATE:
        return pcm_bytes

    audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
    orig_len = len(audio_int16)
    if orig_len == 0:
        return b""

    target_len = int(round(orig_len * TARGET_SAMPLE_RATE / src_samplerate))
    orig_indices = np.linspace(0, orig_len - 1, orig_len)
    target_indices = np.linspace(0, orig_len - 1, target_len)
    resampled = np.interp(target_indices, orig_indices, audio_int16).astype(np.int16)
    return resampled.tobytes()


class AudioRecorder:
    """Records audio from the default or specified input device at hardware-supported rates."""

    def __init__(self):
        self._buffer = bytearray()
        self._stream: Optional[sd.InputStream] = None
        self._actual_samplerate: int = TARGET_SAMPLE_RATE
        self._lock = threading.Lock()

    def start(self, device: Optional[str] = None) -> None:
        """Open a 16-bit PCM mono InputStream negotiating native device sample rate."""
        with self._lock:
            if self._stream is not None:
                return
            self._buffer.clear()

            # Parse device index if string is integer
            dev_idx = int(device) if device and device.isdigit() else (device or None)

            # Query hardware native rate or test fallback rates
            candidate_rates = [16000, 48000, 44100, 32000, 24000, 8000]
            if dev_idx is not None:
                try:
                    info = sd.query_devices(dev_idx, "input")
                    dev_default_rate = int(info.get("default_samplerate", 48000))
                    if dev_default_rate not in candidate_rates:
                        candidate_rates.insert(0, dev_default_rate)
                    else:
                        candidate_rates.remove(dev_default_rate)
                        candidate_rates.insert(0, dev_default_rate)
                except Exception:
                    pass

            def callback(indata, frames, time_info, status):
                if status:
                    logger.debug("Audio callback status: %s", status)
                self._buffer.extend(indata.tobytes())

            stream = None
            used_rate = TARGET_SAMPLE_RATE

            for rate in candidate_rates:
                try:
                    stream = sd.InputStream(
                        samplerate=rate,
                        channels=1,
                        dtype=np.int16,
                        device=dev_idx,
                        callback=callback,
                    )
                    stream.start()
                    used_rate = rate
                    break
                except Exception as err:
                    logger.debug("Sample rate %d Hz not supported on device %s: %s", rate, dev_idx, err)
                    stream = None

            if stream is None:
                logger.error("Failed to open audio input stream on device %s across all sample rates.", dev_idx)
                self._stream = None
                return

            self._stream = stream
            self._actual_samplerate = used_rate
            logger.info("Audio recording stream started on device: %s at %d Hz", dev_idx or "default", used_rate)

    def stop(self) -> bytes:
        """Stop recording, resample to 16kHz mono PCM, and return bytes."""
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

            raw_data = bytes(self._buffer)
            self._buffer.clear()

            # Resample to exactly 16000 Hz for Parakeet
            resampled_data = resample_to_16k(raw_data, self._actual_samplerate)
            logger.info(
                "Audio recording captured %d raw bytes (%d Hz) -> %d bytes at 16kHz",
                len(raw_data),
                self._actual_samplerate,
                len(resampled_data),
            )
            return resampled_data

    @property
    def is_recording(self) -> bool:
        return self._stream is not None
