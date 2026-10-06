"""Tests for parakeet_cage.audio"""
import shutil
import time

import pytest

from parakeet_cage.audio import AudioRecorder


def test_recorder_start_stop_returns_bytes():
    """Verify API contract: start sets state, stop returns bytes."""
    rec = AudioRecorder()
    rec.start(device="")
    assert rec.is_recording is True
    time.sleep(0.1)
    data = rec.stop()
    assert isinstance(data, bytes)


def test_stop_without_start_returns_empty():
    rec = AudioRecorder()
    assert rec.stop() == b""

