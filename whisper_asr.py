"""
Offline ASR using faster-whisper (CTranslate2-optimized Whisper).

Transcribes audio segments detected by VAD into text.
Includes hallucination detection to suppress known Whisper artifacts.
"""

import os
import re
from collections import Counter

import numpy as np
import logging
from faster_whisper import WhisperModel

import config

logger = logging.getLogger(__name__)

LANG_MAP = {
    "en": "en",
    "ja": "ja",
    "hi": "hi",
}


class WhisperASR:
    """Offline speech-to-text using faster-whisper."""

    def __init__(self):
        self.model: WhisperModel | None = None

    def load(self):
        model_size = config.WHISPER_MODEL_SIZE

        device = config.WHISPER_DEVICE
        compute_type = config.WHISPER_COMPUTE_TYPE

        if device == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"

        if compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"

        # On CPU, ctranslate2 defaults to using every logical core for
        # inference — that starves the real-time mic/loopback audio
        # callback threads of scheduling time, which is what causes
        # "input overflow" (dropped audio) during transcription. Leaving
        # a couple of cores free keeps audio capture responsive. Doesn't
        # apply on GPU, where inference doesn't compete for CPU cores.
        cpu_threads = max(2, (os.cpu_count() or 4) - 2) if device == "cpu" else 0

        logger.info(
            f"Loading Whisper model: size={model_size}, "
            f"device={device}, compute_type={compute_type}"
            + (f", cpu_threads={cpu_threads}" if device == "cpu" else "")
        )

        try:
            self.model = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
                cpu_threads=cpu_threads,
            )
            logger.info("Whisper model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            if device == "cuda":
                logger.info("Retrying with CPU...")
                self.model = WhisperModel(
                    model_size,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=max(2, (os.cpu_count() or 4) - 2),
                )
                logger.info("Whisper model loaded on CPU")

    def _run_whisper(self, audio: np.ndarray, language: str,
                     task: str = "transcribe", fast: bool = False) -> str:
        """
        Internal: run a single Whisper pass and return the text.

        Args:
            audio: Audio samples (float32)
            language: Source language code
            task: "transcribe" or "translate"
            fast: If True, use minimal beam_size for speed
        """
        whisper_lang = LANG_MAP.get(language, language)

        is_cpu = (self.model.model.device == "cpu") if hasattr(self.model, 'model') else True
        if fast:
            beam, best = 1, 1
        else:
            beam = 2 if is_cpu else 5
            best = 1 if is_cpu else 3

        segments, info = self.model.transcribe(
            audio,
            language=whisper_lang,
            task=task,
            beam_size=beam,
            best_of=best,
            vad_filter=False,
            without_timestamps=True,
            condition_on_previous_text=False,
            no_speech_threshold=config.WHISPER_NO_SPEECH_THRESHOLD,
            log_prob_threshold=config.WHISPER_LOG_PROB_THRESHOLD,
        )

        texts = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                if hasattr(segment, 'avg_logprob') and segment.avg_logprob < config.WHISPER_LOG_PROB_THRESHOLD:
                    logger.debug(
                        f"ASR: discarding low-confidence segment: \"{text}\" "
                        f"(avg_logprob={segment.avg_logprob:.2f})"
                    )
                    continue
                if hasattr(segment, 'no_speech_prob') and segment.no_speech_prob > config.WHISPER_NO_SPEECH_THRESHOLD:
                    logger.debug(
                        f"ASR: discarding no-speech segment: \"{text}\" "
                        f"(no_speech_prob={segment.no_speech_prob:.2f})"
                    )
                    continue
                texts.append(text)

        full_text = " ".join(texts)

        logger.debug(
            f"ASR [{whisper_lang}, task={task}]: \"{full_text[:80]}\" "
            f"(prob={info.language_probability:.2f})"
        )

        return full_text

    def transcribe(self, audio: np.ndarray, language: str, target_lang: str = "en") -> str:
        """Single-pass transcribe or translate. Returns one text string."""
        if self.model is None:
            raise RuntimeError("Whisper model not loaded. Call load() first.")

        rms = float(np.sqrt(np.mean(audio ** 2)))
        if rms < config.MIN_UTTERANCE_ENERGY:
            return ""

        task = "translate" if language != "en" else "transcribe"

        try:
            full_text = self._run_whisper(audio, language, task=task)
            if not full_text or self._is_hallucination(full_text):
                if full_text:
                    logger.info(f"ASR: filtered hallucination: \"{full_text}\"")
                return ""
            return full_text
        except Exception as e:
            logger.error(f"ASR transcription error: {e}")
            return ""

    def transcribe_and_translate(self, audio: np.ndarray,
                                 language: str) -> tuple[str, str]:
        """
        Two-pass ASR for non-English audio:
          1. task="transcribe" → source language text (e.g. Hindi)
          2. task="translate"  → English translation

        For English audio, only transcribes (no translation needed).

        Returns:
            (source_text, english_text) — either may be empty string
        """
        if self.model is None:
            raise RuntimeError("Whisper model not loaded. Call load() first.")

        rms = float(np.sqrt(np.mean(audio ** 2)))
        if rms < config.MIN_UTTERANCE_ENERGY:
            return "", ""

        try:
            if language == "en":
                # English audio: just transcribe, no translation
                text = self._run_whisper(audio, language, task="transcribe")
                if not text or self._is_hallucination(text):
                    if text:
                        logger.info(f"ASR: filtered hallucination: \"{text}\"")
                    return "", ""
                return text, text

            # Non-English: do both passes
            # Pass 1: transcribe in source language (fast mode for speed)
            source_text = self._run_whisper(
                audio, language, task="transcribe", fast=True
            )

            # Pass 2: translate to English (full quality)
            english_text = self._run_whisper(
                audio, language, task="translate", fast=False
            )

            # Apply hallucination filter to the translated text
            if not english_text or self._is_hallucination(english_text):
                if english_text:
                    logger.info(f"ASR: filtered hallucination: \"{english_text}\"")
                return "", ""

            logger.info(
                f"ASR [{language}→en]: \"{source_text[:50]}\" → \"{english_text[:50]}\""
            )

            return source_text, english_text

        except Exception as e:
            logger.error(f"ASR transcribe_and_translate error: {e}")
            return "", ""

    @staticmethod
    def _is_hallucination(text: str) -> bool:
        """
        Detect common Whisper hallucination patterns:
        1. Known hallucination phrases ("mainstream", "thank you", etc.)
        2. Excessive word repetition ("word word word word")
        """
        clean = text.strip().lower()
        # Remove punctuation for comparison
        clean = re.sub(r'[^\w\s]', '', clean).strip()

        if not clean:
            return True

        # Check against known hallucination patterns
        for pattern in config.HALLUCINATION_PATTERNS:
            if clean == pattern.lower():
                return True
            # Also catch repeated patterns like "mainstream mainstream mainstream"
            if clean.replace(pattern.lower(), '').strip() == '':
                return True

        # Check for excessive word repetition
        words = clean.split()
        if len(words) >= 2:
            counter = Counter(words)
            most_common_count = counter.most_common(1)[0][1]
            repeat_ratio = most_common_count / len(words)
            if repeat_ratio >= config.HALLUCINATION_REPEAT_RATIO:
                return True

        # Very short single-character or single-word outputs are suspicious
        if len(clean) <= 2:
            return True

        return False
