"""
Audio processing channel pipeline.

Each channel (mic, loopback) has its own pipeline:
  Audio Queue -> VAD -> Utterance Queue -> ASR -> Translation -> Subtitles + TTS

VAD runs continuously in its own task so audio is NEVER dropped during
ASR/translation. The utterance queue decouples the two stages.

Runs as an async task, consuming audio chunks from the capture queue.
"""

import asyncio
import numpy as np
import logging
import time
import concurrent.futures

from vad_engine import SileroVAD
from whisper_asr import WhisperASR
from argos_translate import translate_text
from piper_tts import PiperTTS
from subtitles import SubtitleDisplay
from audio_player import AudioPlayer

import config

logger = logging.getLogger(__name__)

# Thread pool for CPU-bound work (ASR, Translation, TTS)
_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="pipeline"
)


class ChannelPipeline:
    """
    Processing pipeline for one audio channel.

    Two decoupled async tasks:
    1. VAD task: continuously reads audio chunks -> emits complete utterances
    2. ASR task: picks up utterances -> ASR -> translate -> output

    This ensures audio is NEVER dropped while ASR/translation is running.
    """

    def __init__(
        self,
        name: str,
        audio_queue: asyncio.Queue,
        source_lang: str,
        target_lang: str,
        vad: SileroVAD,
        asr: WhisperASR,
        tts: PiperTTS,
        subtitles: SubtitleDisplay,
        audio_player: AudioPlayer,
    ):
        self.name = name
        self.audio_queue = audio_queue
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.vad = vad
        self.asr = asr
        self.tts = tts
        self.subtitles = subtitles
        self.audio_player = audio_player
        self._running = False
        # Internal queue between VAD task and ASR task (max 10 utterances buffered)
        self._utterance_queue: asyncio.Queue = asyncio.Queue(maxsize=10)

    async def _vad_task(self, channel_vad: SileroVAD):
        """
        Continuously reads raw audio chunks and runs VAD.
        Emits complete utterances into _utterance_queue.
        This runs independently of ASR so audio is never dropped.
        """
        while self._running:
            try:
                try:
                    audio_chunk = await asyncio.wait_for(
                        self.audio_queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                utterance = channel_vad.process_chunk(audio_chunk)

                if utterance is not None:
                    logger.debug(
                        f"[{self.name}] VAD: utterance ready "
                        f"{len(utterance)/config.SAMPLE_RATE:.2f}s"
                    )
                    # Drop oldest if queue is full (ASR is too slow)
                    if self._utterance_queue.full():
                        try:
                            self._utterance_queue.get_nowait()
                            logger.warning(
                                f"[{self.name}] Utterance queue full, dropped oldest"
                            )
                        except asyncio.QueueEmpty:
                            pass
                    await self._utterance_queue.put(utterance)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"VAD task [{self.name}] error: {e}", exc_info=True)
                await asyncio.sleep(0.05)

    async def _asr_task(self, loop: asyncio.AbstractEventLoop):
        """
        Picks up complete utterances and runs ASR -> translation -> output.
        Runs independently so VAD keeps collecting audio while this processes.
        """
        while self._running:
            try:
                try:
                    utterance = await asyncio.wait_for(
                        self._utterance_queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                logger.debug(
                    f"[{self.name}] Processing utterance: "
                    f"{len(utterance)/config.SAMPLE_RATE:.2f}s"
                )

                # Run ASR in thread pool (CPU-intensive)
                transcript = await loop.run_in_executor(
                    _executor,
                    self.asr.transcribe,
                    utterance,
                    self.source_lang,
                )

                if not transcript or not transcript.strip():
                    continue

                # Translate in thread pool
                translated = await loop.run_in_executor(
                    _executor,
                    translate_text,
                    transcript,
                    self.source_lang,
                    self.target_lang,
                )

                if not translated:
                    continue

                # Output: subtitles
                self.subtitles.show(
                    channel=self.name,
                    original=transcript,
                    translated=translated,
                    source_lang=self.source_lang,
                    target_lang=self.target_lang,
                )

                # Output: TTS (synthesize in thread pool, then queue for playback)
                if config.ENABLE_TTS_OUTPUT:
                    tts_audio = await loop.run_in_executor(
                        _executor,
                        self.tts.synthesize,
                        translated,
                        self.target_lang,
                    )
                    if tts_audio is not None:
                        self.audio_player.play(tts_audio)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"ASR task [{self.name}] error: {e}", exc_info=True)
                await asyncio.sleep(0.1)

    async def run(self):
        """
        Main pipeline: starts VAD and ASR as two concurrent tasks.
        VAD continuously collects audio; ASR processes utterances independently.
        """
        self._running = True
        logger.info(
            f"Pipeline [{self.name}] started: "
            f"{self.source_lang} -> {self.target_lang}"
        )

        # Each channel gets its own VAD instance (they track state independently)
        channel_vad = SileroVAD()
        channel_vad.load()

        loop = asyncio.get_event_loop()

        # Run both tasks concurrently — VAD never blocks on ASR
        vad_coro = self._vad_task(channel_vad)
        asr_coro = self._asr_task(loop)

        try:
            await asyncio.gather(vad_coro, asr_coro)
        except asyncio.CancelledError:
            pass

        logger.info(f"Pipeline [{self.name}] stopped")

    def stop(self):
        """Signal the pipeline to stop."""
        self._running = False
