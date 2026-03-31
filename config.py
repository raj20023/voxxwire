"""
Configuration for Real-Time Offline Speech Translator.
Edit these values to match your system and language needs.
"""

import os

# Path for persisted user settings (saved/loaded automatically)
SETTINGS_FILE: str = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "user_settings.json"
)

# =============================================================================
# AUDIO DEVICE SETTINGS
# Run `python list_devices.py` to find your device indices
# =============================================================================

# Microphone device index (None = system default)
# Device [1] = Microphone (2- Realtek(R) Audio) — your default mic
MIC_DEVICE_INDEX: int | None = 1

# System audio loopback device index
# Device [28] = Stereo Mix (Realtek HD Audio Stereo input) — captures system audio
# This is more reliable than WASAPI loopback on most systems.
# Alternative: use device [14] (WASAPI Headphones output) for WASAPI loopback mode
LOOPBACK_DEVICE_INDEX: int | None = 28

# Whether the loopback device is a regular input (like Stereo Mix)
# or a WASAPI output device that needs loopback mode.
# Set True for device [28] Stereo Mix, False for device [14] WASAPI output
LOOPBACK_IS_INPUT_DEVICE: bool = True

# Audio sample rate (16000 is optimal for speech recognition)
SAMPLE_RATE: int = 16000

# Audio chunk duration in milliseconds
# Smaller = lower latency but more CPU. 30ms is good for VAD.
CHUNK_DURATION_MS: int = 30

# Microphone input gain multiplier (1.0 = no boost, 2.0 = double amplitude)
# Increase if voice is not being detected at normal speaking distance
MIC_GAIN: float = 2.5

# =============================================================================
# LANGUAGE SETTINGS
# =============================================================================

# What language YOU speak into the microphone
MIC_SOURCE_LANG: str = "en"  # "en", "ja", "hi"

# What language to translate YOUR speech into (for remote participants)
MIC_TARGET_LANG: str = "ja"  # "en", "ja", "hi"

# What language the REMOTE participants speak (system audio)
LOOPBACK_SOURCE_LANG: str = "ja"  # "en", "ja", "hi"

# What language to translate REMOTE speech into (for you)
LOOPBACK_TARGET_LANG: str = "en"  # "en", "ja", "hi"

# Language display names (for subtitles)
LANG_NAMES: dict[str, str] = {
    "en": "English",
    "ja": "Japanese",
    "hi": "Hindi",
}

# =============================================================================
# WHISPER ASR SETTINGS
# =============================================================================

# Model size: "tiny", "base", "small", "medium", "large-v3"
# Larger = more accurate but slower. "small" is a good balance.
# "large-v3" recommended if you have a good GPU.
WHISPER_MODEL_SIZE: str = "small"

# Device for whisper: "cuda" (GPU) or "cpu"
# Auto-detect: will try cuda first, fall back to cpu
WHISPER_DEVICE: str = "auto"

# Compute type: "float16" (GPU), "int8" (CPU fast), "float32" (CPU accurate)
WHISPER_COMPUTE_TYPE: str = "auto"

# Minimum audio duration (seconds) to send to ASR
# Prevents sending tiny fragments
MIN_SPEECH_DURATION_S: float = 0.5  # Minimum utterance length to avoid noise-as-speech

# Maximum audio buffer before forcing ASR (seconds)
# Shorter chunks process faster on CPU, reducing pipeline backlog.
# With utterance merging in channel.py, shorter chunks get batched
# automatically when ASR falls behind.
MAX_SPEECH_DURATION_S: float = 8.0

# =============================================================================
# VAD SETTINGS (Silero)
# =============================================================================

# Speech probability threshold (0.0 - 1.0)
# Higher = more conservative (fewer false triggers)
VAD_THRESHOLD: float = 0.35  # Balanced: avoids false triggers on ambient noise

# Minimum silence duration (ms) to consider speech ended
VAD_MIN_SILENCE_MS: int = 500  # Reduced for snappier response

# Speech padding (ms) — audio kept before/after detected speech
VAD_SPEECH_PAD_MS: int = 100

# =============================================================================
# HALLUCINATION FILTER SETTINGS
# =============================================================================

# Minimum RMS energy for an utterance to be sent to ASR
# Utterances below this are likely silence/noise and would cause hallucinations
MIN_UTTERANCE_ENERGY: float = 0.005

# Whisper no_speech_threshold: if the no-speech probability is above this,
# the segment is treated as silence (higher = more permissive)
WHISPER_NO_SPEECH_THRESHOLD: float = 0.5

# Whisper log_prob_threshold: segments with average log probability below
# this value are discarded (helps filter low-confidence hallucinations)
WHISPER_LOG_PROB_THRESHOLD: float = -1.0

# Known Whisper hallucination patterns (case-insensitive substrings)
# If the entire transcript matches one of these, it is discarded
HALLUCINATION_PATTERNS: list[str] = [
    "mainstream",
    "thank you",
    "thanks for watching",
    "subscribe",
    "like and subscribe",
    "please subscribe",
    "you",
    "the",
    "i'm sorry",
    "bye",
    "subtitles by",
    "amara.org",
]

# Maximum ratio of repeated words in a transcript to consider it a hallucination
# e.g. "mainstream mainstream mainstream" has ratio 1.0 (all same word)
HALLUCINATION_REPEAT_RATIO: float = 0.6

# =============================================================================
# TRANSLATION SETTINGS (Argos)
# =============================================================================

# Nothing to configure — language packs are installed by setup_languages.py

# =============================================================================
# TTS SETTINGS (Piper)
# =============================================================================

# Directory where Piper voice models are stored
PIPER_VOICES_DIR: str = "piper_voices"

# Voice model names per language (downloaded by setup_tts_voices.py)
# These are Piper ONNX voice model filenames (without .onnx extension)
# NOTE: Japanese voices are NOT available in standard Piper. Japanese TTS is disabled.
#       Subtitles will still work for Japanese output.
PIPER_VOICE_MODELS: dict[str, str] = {
    "en": "en_US-lessac-medium",
    "hi": "hi_IN-rohan-medium",   # If this failed, try "hi_IN-pratham-medium"
    # "ja": no official Piper voice available — Japanese TTS disabled
}

# TTS speech rate (words per minute multiplier, 1.0 = normal)
TTS_SPEED: float = 1.0

# =============================================================================
# FEEDBACK LOOP PREVENTION
# =============================================================================

# Extra silence (seconds) after TTS playback before re-enabling loopback capture
# This prevents capturing the tail end of TTS playback
FEEDBACK_GATE_BUFFER_S: float = 0.3

# =============================================================================
# PIPELINE SETTINGS
# =============================================================================

# Maximum items in audio processing queues before dropping old data
QUEUE_MAX_SIZE: int = 50

# Enable/disable channels
ENABLE_MIC_CHANNEL: bool = True
ENABLE_LOOPBACK_CHANNEL: bool = True

# Enable/disable outputs
ENABLE_SUBTITLES: bool = True
ENABLE_TTS_OUTPUT: bool = True

# Subtitle display settings
SUBTITLE_MAX_LINES: int = 6
