"""
System audio loopback capture using WASAPI (via pyaudiowpatch).

Captures the actual audio being rendered to your speakers/headphones as
its own dedicated loopback device — a genuinely separate signal path from
the microphone, so the mic and remote channels can never bleed into each
other the way a misconfigured "Stereo Mix"-style input device would.
"""

import asyncio
import numpy as np
import pyaudiowpatch as pyaudio
import logging
import time

import config

logger = logging.getLogger(__name__)


class LoopbackCapture:
    """
    Captures system audio via WASAPI loopback.

    Includes a feedback gate: when TTS is playing translated audio,
    capture is suppressed to prevent infinite translation loops.
    """

    def __init__(self, audio_queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        self.audio_queue = audio_queue
        self.loop = loop
        self.device_index = config.LOOPBACK_DEVICE_INDEX

        self._pa: pyaudio.PyAudio | None = None
        self.stream = None
        self._keepalive_stream = None
        self._running = False
        self._native_sr: int | None = None
        self._channels: int | None = None

        # Feedback gate: timestamp until which loopback is muted
        self._gate_until: float = 0.0

    def set_gate(self, duration_s: float):
        """
        Mute loopback capture for the given duration.
        Called by the TTS audio player when it starts playing.
        """
        gate_end = time.monotonic() + duration_s + config.FEEDBACK_GATE_BUFFER_S
        self._gate_until = max(self._gate_until, gate_end)
        logger.debug(f"Loopback gate set for {duration_s:.2f}s + buffer")

    @property
    def is_gated(self) -> bool:
        return time.monotonic() < self._gate_until

    def _resolve_device_index(self) -> int:
        """Pick the configured loopback device, or fall back to the
        loopback counterpart of the current default output device."""
        if self.device_index is not None:
            return self.device_index

        wasapi_info = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_speakers = self._pa.get_device_info_by_index(wasapi_info["defaultOutputDevice"])

        if default_speakers.get("isLoopbackDevice"):
            return default_speakers["index"]

        for loopback in self._pa.get_loopback_device_info_generator():
            if default_speakers["name"] in loopback["name"]:
                return loopback["index"]

        raise RuntimeError(
            "No WASAPI loopback device found for the default output device "
            f"'{default_speakers['name']}'."
        )

    def _find_real_output_device(self, loopback_device_info: dict) -> dict | None:
        """Find the physical output device a loopback device mirrors, by
        matching host API + name (loopback devices are named
        '<output device name> [Loopback]')."""
        base_name = loopback_device_info["name"].replace(" [Loopback]", "")
        host_api = loopback_device_info["hostApi"]
        for i in range(self._pa.get_device_count()):
            d = self._pa.get_device_info_by_index(i)
            if (d["hostApi"] == host_api and d["name"] == base_name
                    and d["maxOutputChannels"] > 0 and not d.get("isLoopbackDevice")):
                return d
        return None

    @staticmethod
    def _silence_callback(in_data, frame_count, time_info, status):
        return (b"\x00" * frame_count * 2 * 4, pyaudio.paContinue)  # stereo float32 silence

    def _start_keepalive(self, loopback_device_info: dict):
        """
        WASAPI's shared-mode audio engine can idle the render graph when
        nothing is actually playing — when that happens the loopback
        capture stream stops receiving callbacks entirely (not just
        silence, literally zero) until real audio resumes, and sometimes
        doesn't recover on its own. Playing a continuous silent stream on
        the mirrored output device keeps the engine awake so loopback
        capture never stalls during quiet periods.
        """
        try:
            real_output = self._find_real_output_device(loopback_device_info)
            if real_output is None:
                logger.warning(
                    "Could not find the physical output device behind "
                    f"'{loopback_device_info['name']}' — loopback capture may "
                    "stall during silence."
                )
                return

            self._keepalive_stream = self._pa.open(
                format=pyaudio.paFloat32,
                channels=2,
                rate=int(real_output["defaultSampleRate"]),
                output=True,
                output_device_index=real_output["index"],
                stream_callback=self._silence_callback,
            )
            self._keepalive_stream.start_stream()
            logger.info(f"Loopback keep-alive stream started on '{real_output['name']}'")
        except Exception as e:
            logger.warning(f"Could not start loopback keep-alive stream: {e}")

    def _callback(self, in_data, frame_count, time_info, status):
        if not self._running or self.is_gated:
            return (None, pyaudio.paContinue)

        audio = np.frombuffer(in_data, dtype=np.float32)
        if self._channels > 1:
            audio = audio.reshape(-1, self._channels).mean(axis=1)

        target_sr = config.SAMPLE_RATE
        if self._native_sr != target_sr and len(audio) > 1:
            ratio = target_sr / self._native_sr
            new_len = int(len(audio) * ratio)
            indices = np.linspace(0, len(audio) - 1, new_len)
            audio = np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)

        def _safe_put(chunk=audio):
            if not self.audio_queue.full():
                try:
                    self.audio_queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    pass

        try:
            self.loop.call_soon_threadsafe(_safe_put)
        except RuntimeError:
            pass  # Event loop closed

        return (None, pyaudio.paContinue)

    def start(self):
        self._pa = pyaudio.PyAudio()

        try:
            device_index = self._resolve_device_index()
            device_info = self._pa.get_device_info_by_index(device_index)

            if not device_info.get("isLoopbackDevice"):
                raise RuntimeError(
                    f"Device [{device_index}] '{device_info['name']}' is not a WASAPI "
                    "loopback device — pick one of the '[Loopback]' devices for system audio."
                )

            self._native_sr = int(device_info["defaultSampleRate"])
            self._channels = int(device_info["maxInputChannels"])

            logger.info(
                f"Starting loopback capture (WASAPI): device=[{device_index}] "
                f"{device_info['name']}, sr={self._native_sr}, ch={self._channels}"
            )

            self._running = True
            self.stream = self._pa.open(
                format=pyaudio.paFloat32,
                channels=self._channels,
                rate=self._native_sr,
                input=True,
                input_device_index=device_index,
                stream_callback=self._callback,
            )
            self.stream.start_stream()
            logger.info(f"Loopback capture started via WASAPI loopback (sr: {self._native_sr})")

            self._start_keepalive(device_info)
        except Exception as e:
            self._running = False
            if self._pa is not None:
                self._pa.terminate()
                self._pa = None
            raise RuntimeError(
                f"Cannot capture system audio loopback device [{self.device_index}]: {e}"
            )

    def stop(self):
        self._running = False
        if self.stream is not None:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception as e:
                logger.warning(f"Error stopping loopback stream: {e}")
            self.stream = None
        if self._keepalive_stream is not None:
            try:
                self._keepalive_stream.stop_stream()
                self._keepalive_stream.close()
            except Exception as e:
                logger.warning(f"Error stopping loopback keep-alive stream: {e}")
            self._keepalive_stream = None
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception as e:
                logger.warning(f"Error terminating loopback PyAudio: {e}")
            self._pa = None
        logger.info("Loopback capture stopped")
