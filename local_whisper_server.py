import os
import re
import threading
import time
from typing import Optional

import ctranslate2
import numpy as np
import sounddevice as sd
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from faster_whisper import WhisperModel

HOST = "127.0.0.1"
PORT = int(os.getenv("VOXHING_PORT", "8765"))
TOKEN = os.getenv("VOXHING_TOKEN", "vikash-local-whisper-v1")
MODEL_NAME = os.getenv("WHISPER_MODEL", "turbo")
SAMPLE_RATE = 16000
CHANNELS = 1
SILENCE_SECONDS = float(os.getenv("VOXHING_SILENCE_SECONDS", "1.0"))
SILENCE_RMS = float(os.getenv("VOXHING_SILENCE_RMS", "0.012"))
NO_SPEECH_TIMEOUT = float(os.getenv("VOXHING_NO_SPEECH_TIMEOUT", "10"))
MAX_RECORD_SECONDS = float(os.getenv("VOXHING_MAX_RECORD_SECONDS", "30"))

HINGLISH_PROMPT = (
    "Mai Hindi aur English naturally mix karke Roman letters mein baat karta hu. "
    "Aur kaise ho tum? Mai Vikash hu. Kal mujhe Jalandhar jana hai. "
    "Mera friend Bengaluru ke Mahadevapura area mein rehta hai. "
    "Haryana se Chandigarh jana hai. Jammu Kashmir ka weather thanda hai. "
    "Mujhe office meeting ke baad phone karna. Mera number 123456 hai. "
    "Mai kal Bengaluru jaunga aur phir tumhe call karunga."
)

ENGLISH_PROMPT = (
    "Indian English dictation. Bengaluru, Mahadevapura, Haryana, Jammu Kashmir, "
    "Jalandhar, Ludhiana, Chandigarh, Gurugram, Ghaziabad, Hyderabad, Visakhapatnam."
)

HINDI_PROMPT = (
    "मैं हिंदी में साफ़ तरीके से बोल रहा हूँ। आज मुझे दिल्ली जाना है और कल चंडीगढ़ जाना है।"
)

DIGITS = {
    "zero": "0", "oh": "0", "o": "0", "one": "1", "two": "2", "three": "3",
    "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ek": "1", "do": "2", "teen": "3", "char": "4", "chaar": "4", "panch": "5",
    "paanch": "5", "che": "6", "chhe": "6", "saat": "7", "aath": "8", "nau": "9",
    "एक": "1", "दो": "2", "तीन": "3", "चार": "4", "पांच": "5", "पाँच": "5",
    "छह": "6", "सात": "7", "आठ": "8", "नौ": "9", "वन": "1", "टू": "2",
    "थ्री": "3", "फोर": "4", "फाइव": "5", "सिक्स": "6", "सेवन": "7",
    "एट": "8", "नाइन": "9", "जीरो": "0", "ज़ीरो": "0",
}
REPEAT_WORDS = {"double": 2, "triple": 3, "डबल": 2, "ट्रिपल": 3}


def normalize_token(token: str) -> str:
    return re.sub(r"^[^\w\u0900-\u097F]+|[^\w\u0900-\u097F]+$", "", token.lower(), flags=re.UNICODE)


def spoken_digits_to_numbers(text: str) -> str:
    words = text.split()
    out = []
    i = 0
    while i < len(words):
        pieces = []
        j = i
        while j < len(words):
            current = normalize_token(words[j])
            if current in REPEAT_WORDS and j + 1 < len(words):
                nxt = normalize_token(words[j + 1])
                if nxt in DIGITS:
                    pieces.append(DIGITS[nxt] * REPEAT_WORDS[current])
                    j += 2
                    continue
            if current in DIGITS:
                pieces.append(DIGITS[current])
                j += 1
                continue
            break

        joined = "".join(pieces)
        if len(joined) >= 2:
            out.append(joined)
            i = j
        else:
            out.append(words[i])
            i += 1
    return re.sub(r"\s+", " ", " ".join(out)).strip()


def collapse_phrase_loop(text: str) -> str:
    words = text.split()
    count = len(words)
    if count < 6:
        return text
    normalized = [re.sub(r"\W+", "", word.lower()) for word in words]
    for size in range(2, count // 3 + 1):
        if count % size:
            continue
        if count // size < 3:
            continue
        phrase = normalized[:size]
        if all(normalized[index] == phrase[index % size] for index in range(count)):
            return " ".join(words[:size])
    return text


def cleanup_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = collapse_phrase_loop(text)
    text = spoken_digits_to_numbers(text)
    return text.strip()


def load_model() -> WhisperModel:
    cpu_threads = max(2, (os.cpu_count() or 4) - 1)
    try:
        if ctranslate2.get_cuda_device_count() > 0:
            print(f"[VoxHing] Loading {MODEL_NAME} on NVIDIA CUDA...")
            try:
                return WhisperModel(MODEL_NAME, device="cuda", compute_type="float16", cpu_threads=cpu_threads)
            except Exception as exc:
                print(f"[VoxHing] CUDA load failed; using CPU instead: {exc}")
    except Exception:
        pass

    print(f"[VoxHing] Loading {MODEL_NAME} on CPU (int8)...")
    return WhisperModel(MODEL_NAME, device="cpu", compute_type="int8", cpu_threads=cpu_threads)


print("[VoxHing] Starting model load. First launch may download the model...")
MODEL = load_model()
print("[VoxHing] Model ready.")


class StartRequest(BaseModel):
    mode: str = "HING"
    context: Optional[str] = None


class RecorderState:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.job_id = 0
        self.state = "idle"
        self.text = ""
        self.error = ""
        self.detected_language = ""
        self.mode = "HING"

    def snapshot(self):
        with self.lock:
            return {
                "ok": True,
                "job_id": self.job_id,
                "state": self.state,
                "text": self.text,
                "error": self.error,
                "detected_language": self.detected_language,
                "mode": self.mode,
            }


STATE = RecorderState()
app = FastAPI(title="VoxHing Local Whisper Server")


def check_token(value: Optional[str]):
    if value != TOKEN:
        raise HTTPException(status_code=401, detail="Bad local VoxHing token")


def choose_prompt(mode: str, context: str = ""):
    mode = mode.upper()
    context = re.sub(r"\s+", " ", context).strip()[:160]
    if mode == "HI":
        return "hi", HINDI_PROMPT
    if mode == "EN":
        return "en", ENGLISH_PROMPT + (f" {context}" if context else "")
    return None, HINGLISH_PROMPT + (f" {context}" if context else "")


def recorder_worker(job_id: int, mode: str, context: str):
    chunks = []
    started = time.monotonic()
    last_voice = started
    heard_speech = False

    def callback(indata, frames, time_info, status):
        nonlocal last_voice, heard_speech
        if status:
            print("[VoxHing] Audio status:", status)
        mono = np.asarray(indata[:, 0], dtype=np.float32).copy()
        chunks.append(mono)
        rms = float(np.sqrt(np.mean(np.square(mono)) + 1e-12))
        if rms >= SILENCE_RMS:
            heard_speech = True
            last_voice = time.monotonic()

    try:
        with STATE.lock:
            if STATE.job_id != job_id:
                return
            STATE.state = "recording"
            STATE.error = ""
            STATE.text = ""
            STATE.detected_language = ""

        print(f"[VoxHing] Recording job {job_id} ({mode})...")
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            callback=callback,
            blocksize=1024,
        ):
            while not STATE.stop_event.is_set():
                now = time.monotonic()
                elapsed = now - started
                if elapsed >= MAX_RECORD_SECONDS:
                    break
                if heard_speech and now - last_voice >= SILENCE_SECONDS:
                    break
                if not heard_speech and elapsed >= NO_SPEECH_TIMEOUT:
                    break
                time.sleep(0.04)

        if not chunks or not heard_speech:
            with STATE.lock:
                if STATE.job_id == job_id:
                    STATE.state = "done"
                    STATE.text = ""
            return

        audio = np.concatenate(chunks).astype(np.float32, copy=False)
        with STATE.lock:
            if STATE.job_id != job_id:
                return
            STATE.state = "transcribing"

        language, prompt = choose_prompt(mode, context)
        print(f"[VoxHing] Transcribing job {job_id}; language={language or 'auto'}")
        segments, info = MODEL.transcribe(
            audio,
            language=language,
            task="transcribe",
            beam_size=5,
            temperature=0.0,
            initial_prompt=prompt,
            condition_on_previous_text=False,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 350},
            repetition_penalty=1.12,
            no_repeat_ngram_size=3,
            without_timestamps=True,
        )

        text = cleanup_text(" ".join(segment.text.strip() for segment in segments if segment.text.strip()))
        with STATE.lock:
            if STATE.job_id == job_id:
                STATE.state = "done"
                STATE.text = text
                STATE.detected_language = getattr(info, "language", "") or ""
        print(f"[VoxHing] Result: {text}")

    except Exception as exc:
        print("[VoxHing] Error:", repr(exc))
        with STATE.lock:
            if STATE.job_id == job_id:
                STATE.state = "error"
                STATE.error = str(exc)


@app.get("/health")
def health(x_voice_token: Optional[str] = Header(default=None)):
    check_token(x_voice_token)
    return {"ok": True, "model": MODEL_NAME, "sample_rate": SAMPLE_RATE, "state": STATE.snapshot()["state"]}


@app.post("/start")
def start_recording(body: StartRequest, x_voice_token: Optional[str] = Header(default=None)):
    check_token(x_voice_token)
    mode = body.mode.upper().strip()
    if mode not in {"HING", "HI", "EN"}:
        mode = "HING"

    with STATE.lock:
        if STATE.state in {"starting", "recording", "transcribing"}:
            raise HTTPException(status_code=409, detail="VoxHing is already busy")
        STATE.job_id += 1
        job_id = STATE.job_id
        STATE.mode = mode
        STATE.state = "starting"
        STATE.text = ""
        STATE.error = ""
        STATE.detected_language = ""
        STATE.stop_event = threading.Event()

    thread = threading.Thread(
        target=recorder_worker,
        args=(job_id, mode, body.context or ""),
        daemon=True,
    )
    STATE.thread = thread
    thread.start()
    return {"ok": True, "job_id": job_id, "state": "starting"}


@app.post("/stop")
def stop_recording(x_voice_token: Optional[str] = Header(default=None)):
    check_token(x_voice_token)
    STATE.stop_event.set()
    return {"ok": True, "state": STATE.snapshot()["state"]}


@app.get("/status")
def status(x_voice_token: Optional[str] = Header(default=None)):
    check_token(x_voice_token)
    return STATE.snapshot()


if __name__ == "__main__":
    import uvicorn
    print(f"[VoxHing] Local server: http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
