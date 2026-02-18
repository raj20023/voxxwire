"""
Microphone audio capture using sounddevice.

Captures audio from the microphone in real-time and pushes
raw audio chunks (numpy float32 arrays) into a queue for processing.
"""

import asyncio
import numpy as np
import sounddevice as sd
import logging

import config

logger = logging.getLogger(__name__)


class MicCapture:
    """Captures microphone audio and pushes chunks to an async queue."""

    def __init__(self, audio_queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        self.audio_queue = audio_queue
        self.loop = loop
        self.stream: sd.InputStream | None = None
        self._running = False

        self.sample_rate = config.SAMPLE_RATE
        self.channels = 1
        self.block_size = int(self.sample_rate * config.CHUNK_DURATION_MS / 1000)
        self.device_index = config.MIC_DEVICE_INDEX

    def _audio_callback(self, indata: np.ndarray, frames: int,
                        time_info, status: sd.CallbackFlags):
        """Called by sounddevice for each audio chunk. Runs in audio thread."""
        if status:
            logger.warning(f"Mic capture status: {status}")

        if not self._running:
            return

        audio_chunk = indata[:, 0].copy().astype(np.float32)

        # Apply gain boost for better sensitivity at normal speaking distance
        if config.MIC_GAIN != 1.0:
            audio_chunk = np.clip(audio_chunk * config.MIC_GAIN, -1.0, 1.0)

        # Schedule queue put in the async loop — check full first to avoid
        # asyncio logging QueueFull exceptions
        def _safe_put(chunk=audio_chunk):
            if not self.audio_queue.full():
                try:
                    self.audio_queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    pass

        try:
            self.loop.call_soon_threadsafe(_safe_put)
        except RuntimeError:
            pass  # Event loop closed

    def start(self):
        """Start capturing microphone audio."""
        logger.info(
            f"Starting mic capture: device={self.device_index}, "
            f"sr={self.sample_rate}, blocksize={self.block_size}"
        )

        self._running = True

        try:
            self.stream = sd.InputStream(
                device=self.device_index,
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                blocksize=self.block_size,
                callback=self._audio_callback,
            )
            self.stream.start()
            logger.info("Mic capture started successfully")
        except Exception as e:
            logger.error(f"Failed to start mic capture: {e}")
            raise

    def stop(self):
        """Stop capturing."""
        self._running = False
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception as e:
                logger.warning(f"Error stopping mic stream: {e}")
            self.stream = None
        logger.info("Mic capture stopped")