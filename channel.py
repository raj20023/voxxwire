"""
Audio processing channel pipeline.

Each channel (mic, loopback) has its own pipeline:
  Audio Queue -> VAD -> Utterance Queue -> ASR -> Translation -> Subtitles + TTS

VAD runs continuously in its own task so audio is NEVER dropped during
ASR/translation. The utterance queue decouples the two stages.

Each channel gets its own thread pool so mic and loopback pipelines
never starve each other for CPU resources.

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


class ChannelPipeline:
    """
    Processing pipeline for one audio channel.

    Two decoupled async tasks:
    1. VAD task: continuously reads audio chunks -> emits complete utterances
    2. ASR task: picks up utterances -> ASR -> translate -> output

    This ensures audio is NEVER dropped while ASR/translation is running.
    Each channel has its own thread pool to prevent mic/loopback starvation.
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
        # Internal queue between VAD task and ASR task
        # Larger buffer to absorb bursts while ASR processes on CPU
        self._utterance_queue: asyncio.Queue = asyncio.Queue(maxsize=20)
        # Per-channel thread pool: 2 workers (1 ASR + 1 translation concurrently)
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix=f"ch-{name}"
        )

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

        Translation strategy:
        - For non-English source: Whisper uses task="translate" to produce
          English directly (much more accurate than Argos for hi/ja→en).
        - If target is English: we're done, no Argos needed.
        - If target is non-English: use Argos only for en→target
          (a much stronger translation direction for Argos).
        - For English source: Whisper transcribes, Argos translates en→target.
        """
        while self._running:
            try:
                try:
                    utterance = await asyncio.wait_for(
                        self._utterance_queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                # ── Merge queued utterances ──
                # When ASR is slow (CPU), multiple utterances pile up.
                # Merge them into one to reduce total ASR calls.
                max_samples = int(config.MAX_SPEECH_DURATION_S * config.SAMPLE_RATE)
                merged = [utterance]
                total_len = len(utterance)
                while not self._utterance_queue.empty() and total_len < max_samples:
                    try:
                        extra = self._utterance_queue.get_nowait()
                        if total_len + len(extra) > max_samples:
                            break  # don't exceed max duration
                        merged.append(extra)
                        total_len += len(extra)
                    except asyncio.QueueEmpty:
                        break

                if len(merged) > 1:
                    utterance = np.concatenate(merged)
                    logger.info(
                        f"[{self.name}] Merged {len(merged)} utterances -> "
                        f"{len(utterance)/config.SAMPLE_RATE:.2f}s"
                    )
                else:
                    logger.debug(
                        f"[{self.name}] Processing utterance: "
                        f"{len(utterance)/config.SAMPLE_RATE:.2f}s"
                    )

                # Run ASR in thread pool (CPU-intensive)
                # For non-English source, Whisper's translate task outputs English
                transcript = await loop.run_in_executor(
                    self._executor,
                    self.asr.transcribe,
                    utterance,
                    self.source_lang,
                    self.target_lang,
                )

                if not transcript or not transcript.strip():
                    continue

                # Determine if Argos translation is still needed
                if self.source_lang == self.target_lang:
                    # Same language — no translation
                    translated = transcript
                elif self.source_lang != "en" and self.target_lang == "en":
                    # Whisper already produced English via task="translate"
                    translated = transcript
                elif self.source_lang != "en" and self.target_lang != "en":
                    # Whisper produced English; now use Argos for en→target
                    translated = await loop.run_in_executor(
                        self._executor,
                        translate_text,
                        transcript,
                        "en",
                        self.target_lang,
                    )
                else:
                    # English source → non-English target: normal Argos flow
                    translated = await loop.run_in_executor(
                        self._executor,
                        translate_text,
                        transcript,
                        self.source_lang,
                        self.target_lang,
                    )

                if not translated:
                    continue

                # For display: show the original source-language text when available
                # When Whisper translated, 'transcript' is already English, so
                # we show it as the original (which is the best we have)
                original_display = transcript

                # Output: subtitles
                self.subtitles.show(
                    channel=self.name,
                    original=original_display,
                    translated=translated,
                    source_lang=self.source_lang,
                    target_lang=self.target_lang,
                )

                # Output: TTS (synthesize in thread pool, then queue for playback)
                if config.ENABLE_TTS_OUTPUT:
                    tts_audio = await loop.run_in_executor(
                        self._executor,
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
        self._executor.shutdown(wait=False)
