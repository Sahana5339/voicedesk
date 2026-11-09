"""Gnani API helpers: Prisma speech-to-text and Timbre text-to-speech (REST)."""
import os
import struct
import time

import requests

STT_URL = "https://api.vachana.ai/stt/v3"
TTS_URL = "https://api.vachana.ai/api/v1/tts/inference"

# label -> (language_code, model or None for the default Prisma v2.5)
LANGS = {
    "Auto-detect (Prisma v3.0)": ("indic-auto", "prisma-v3.0"),
    "Hindi": ("hi-IN", None), "Kannada": ("kn-IN", None), "English (India)": ("en-IN", None),
    "Tamil": ("ta-IN", None), "Telugu": ("te-IN", None), "Marathi": ("mr-IN", None),
    "Bengali": ("bn-IN", None), "Malayalam": ("ml-IN", None), "Gujarati": ("gu-IN", None),
    "Punjabi": ("pa-IN", None),
}
# Timbre v2.5 voices (each voice has one preferred language) - chosen from the Gnani voice catalog
VOICES = {"hi": ("Chitra", "hi-IN"), "en": ("Kaveri", "en-IN"), "kn": ("Kavin", "kn-IN")}


def transcribe(audio_bytes, language_code="indic-auto", model="prisma-v3.0", api_key=None, filename="audio.wav"):
    """Returns {'text', 'lang', 'model', 'stt_ms'}. Raises on HTTP/API errors."""
    api_key = api_key or os.environ.get("GNANI_API_KEY")
    if not api_key:
        raise RuntimeError("No Gnani API key. Configure GNANI_API_KEY in the .env file.")
    data = {"language_code": language_code}
    if model:
        data["model"] = model
    t0 = time.time()
    r = requests.post(STT_URL, headers={"X-API-Key-ID": api_key},
                      files={"audio_file": (filename, audio_bytes, "audio/wav")}, data=data, timeout=60)
    ms = int((time.time() - t0) * 1000)
    if r.status_code != 200:
        raise RuntimeError(f"Speech-to-text failed ({r.status_code}): {r.text[:200]}")
    j = r.json()
    if not j.get("success", True):
        raise RuntimeError(f"Speech-to-text failed: {j}")
    return {"text": j.get("transcript", ""), "lang": j.get("detected_language_code") or
            (language_code if language_code != "indic-auto" else None),
            "model": j.get("model", model or "prisma-v2.5"), "stt_ms": ms}


def fix_wav(b):
    """Gnani streams WAVs with an 'unknown length' header; browsers can refuse those. Patch real sizes in."""
    if b[:4] != b"RIFF":
        return b
    i = b.find(b"data")
    if i < 0:
        return b
    b = bytearray(b)
    struct.pack_into("<I", b, 4, len(b) - 8)
    struct.pack_into("<I", b, i + 4, len(b) - (i + 8))
    return bytes(b)


def synthesize(text, reply_lang="en", api_key=None):
    """Timbre v2.5 text-to-speech. Returns WAV bytes."""
    api_key = api_key or os.environ.get("GNANI_API_KEY")
    if not api_key:
        raise RuntimeError("No Gnani API key.")
    voice, lang = VOICES.get(reply_lang, VOICES["en"])
    body = {"text": text, "voice": voice, "model": "timbre-v2.5", "language": lang, "speed": 1.0,
            "audio_config": {"sample_rate": 48000, "num_channels": 1, "sample_width": 2,
                             "encoding": "linear_pcm", "container": "wav"}}
    r = requests.post(TTS_URL, headers={"Content-Type": "application/json", "X-API-Key-ID": api_key},
                      json=body, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Text-to-speech failed ({r.status_code}): {r.text[:200]}")
    return fix_wav(r.content)


if __name__ == "__main__":
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(48000), w.writeframes(b"\x00\x01" * 4800)
    good = buf.getvalue()
    bad = bytearray(good)
    struct.pack_into("<I", bad, 4, 0xFFFFFFFF)
    j = bytes(bad).find(b"data")
    struct.pack_into("<I", bad, j + 4, 0xFFFFFFFF)
    fixed = fix_wav(bytes(bad))
    with wave.open(io.BytesIO(fixed)) as w:
        assert w.getnframes() == 4800, w.getnframes()
    print("fix_wav OK")
