# Real-Time Offline Speech Translator (Windows)

🌐 **Live App:** [https://voxxwire.com/](https://voxxwire.com/)

## What This Does
Two-channel real-time speech translator for live meetings:
- **Channel A (Mic):** You speak English → translated to Hindi or Japanese (subtitles + spoken audio)
- **Channel B (System Audio):** Others speak Japanese/Hindi → translated to English (subtitles + spoken audio)

Fully offline. No cloud APIs.

## Architecture
```
Microphone ──→ VAD ──→ ASR (Whisper) ──→ Translate (Argos) ──→ Subtitles + TTS
                                                                        │
System Audio ─→ VAD ──→ ASR (Whisper) ──→ Translate (Argos) ──→ Subtitles + TTS
                                                                        │
                                                              Feedback Gate (mute loopback
                                                              during TTS playback)
```

## Requirements
- Windows 10/11
- Python 3.10 or 3.11 (3.12+ may have compatibility issues with some libs)
- ~4GB RAM minimum (8GB recommended)
- NVIDIA GPU recommended for faster-whisper (CPU works but slower)
- A working microphone
- Stereo Mix or WASAPI loopback capable audio device

## Setup Instructions

### Step 1: Create virtual environment
```bash
python -m venv venv
venv\Scripts\activate
```

### Step 2: Install dependencies
```bash
pip install -r requirements.txt
```

### Step 3: Download language packs for Argos Translate
```bash
python setup_languages.py
```
This downloads offline translation models for EN↔HI and EN↔JA.

### Step 4: Download Piper TTS voices
```bash
python setup_tts_voices.py
```

### Step 5: List your audio devices
```bash
python list_devices.py
```
Note the device indices for your microphone and your loopback/system audio device.

### Step 6: Configure
Edit `config.py` to set:
- `MIC_DEVICE_INDEX` — your microphone
- `LOOPBACK_DEVICE_INDEX` — your system audio / WASAPI loopback device
- Language pair settings

### Step 7: Run
```bash
python main.py
```

## How to Test in a Real Meeting
1. Join a meeting (Zoom, Teams, Google Meet, etc.)
2. Run `python main.py` in a terminal
3. Speak English into your mic → see translated subtitles + hear translated speech
4. When remote participants speak Japanese/Hindi → see English subtitles + hear English speech
5. Press Ctrl+C to stop

## Feedback Loop Prevention
Uses a **timing gate**: when TTS plays translated audio, the loopback capture is
suppressed for the playback duration + 200ms buffer. This prevents the system from
re-capturing and re-translating its own TTS output.

## File Structure
```
realtime-translator/
├── main.py                  # Entry point — runs the pipeline
├── config.py                # All configuration in one place
├── requirements.txt         # Python dependencies
├── setup_languages.py       # Downloads Argos translation models
├── setup_tts_voices.py      # Downloads Piper TTS voices
├── audio/
│   ├── __init__.py
│   ├── devices.py           # List/select audio devices
│   ├── mic_capture.py       # Microphone stream capture
│   └── loopback_capture.py  # System audio WASAPI loopback capture
├── vad/
│   ├── __init__.py
│   └── silero_vad.py        # Voice activity detection
├── asr/
│   ├── __init__.py
│   └── whisper_asr.py       # Streaming ASR with faster-whisper
├── translate/
│   ├── __init__.py
│   └── argos_translate.py   # Offline translation
├── tts/
│   ├── __init__.py
│   └── piper_tts.py         # Offline text-to-speech
├── output/
│   ├── __init__.py
│   ├── subtitles.py         # Terminal subtitle display
│   └── audio_player.py      # Play TTS audio with feedback gate
└── pipeline/
    ├── __init__.py
    └── channel.py           # Processing pipeline for one audio channel
```
