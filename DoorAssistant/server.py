import os
import time
import threading
from typing import Dict, Any, List, Optional

import serial
from serial.tools import list_ports

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from openai import OpenAI
import openai as openai_mod  # for compatibility fallbacks

# Try loading a local .env file if present (optional; safe if missing)
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
    print("[config] .env file loaded via python-dotenv")
except ImportError:
    print("[config] WARNING: python-dotenv not installed. Run: pip install python-dotenv")
except Exception as e:
    print(f"[config] WARNING: Failed to load .env: {e}")

SERIAL_PORT = os.getenv("SERIAL_PORT", "")
BAUD = 115200

USE_LLM = os.getenv("USE_LLM", "0") == "1"

# BLE integration (optional)
ENABLE_BLE = os.getenv("ENABLE_BLE", "0") == "1"
BLE_DEVICE_NAME = os.getenv("BLE_DEVICE_NAME", "")
BLE_DEVICE_ADDRESS = os.getenv("BLE_DEVICE_ADDRESS", "")  # Windows sometimes shows MAC like AA:BB:CC:DD:EE:FF
BLE_SERVICE_UUID = os.getenv("BLE_SERVICE_UUID", "")      # e.g. custom service
BLE_CHAR_UUID = os.getenv("BLE_CHAR_UUID", "")             # characteristic that notifies messages

STT_MODEL = "gpt-4o-mini-transcribe"
LLM_MODEL = "gpt-4o-mini"
EMBEDDINGS_MODEL = "text-embedding-3-small"

# Read OpenAI API key from environment; avoid constructing the client if missing
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
if OPENAI_API_KEY:
    print("[config] OPENAI_API_KEY found. Initializing OpenAI client...")
    client: Optional[OpenAI] = OpenAI(api_key=OPENAI_API_KEY)
    try:
        openai_mod.api_key = OPENAI_API_KEY
    except Exception:
        pass
else:
    print("[config] WARNING: OPENAI_API_KEY not set. Audio transcription will fail.")
    print("[config]   - Check your .env file in the DoorAssistant/ directory")
    print("[config]   - Or set env var: $env:OPENAI_API_KEY='your-key'")
    client = None

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

subscribers: List[List[Dict[str, Any]]] = []

last_items: List[str] = []
last_transcript: str = ""

BASE_ESSENTIALS = ["keys", "wallet", "phone", "ID"]
DEST_ITEMS = {
    "gym": ["water bottle", "towel", "headphones", "gym shoes", "deodorant"],
    "class": ["laptop", "charger", "notebook", "pen"],
    "campus": ["laptop", "charger", "notebook", "pen"],
    "work": ["laptop", "charger", "badge", "lunch"],
    "grocery": ["reusable bags", "shopping list", "wallet"],
    "store": ["reusable bags", "shopping list"],
}

def broadcast(ev: Dict[str, Any]):
    for box in subscribers:
        box.append(ev)

def guess_port() -> str:
    ports = list(list_ports.comports())
    if not ports:
        return ""

    for p in ports:
        desc = (p.description or "").lower()
        if "arduino" in desc or "usb serial" in desc or "ch340" in desc or "cp210" in desc:
            return p.device
    return ports[0].device

def serial_worker():
    global SERIAL_PORT
    if not SERIAL_PORT:
        SERIAL_PORT = guess_port()
    if not SERIAL_PORT:
        print("[serial] No serial ports found.")
        return

    print("[serial] Using port:", SERIAL_PORT)
    ser = serial.Serial(SERIAL_PORT, BAUD, timeout=1)

    while True:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if not line:
            continue
        # print("[serial]", line)
        if line == "EVENT:LEAVING":
            broadcast({"type": "LEAVING", "ts": time.time()})

def ble_worker():
    # Run BLE logic in its own async loop
    try:
        import asyncio
        from bleak import BleakClient, BleakScanner
    except Exception as e:
        print("[ble] bleak not available. Install with: pip install bleak")
        return

    async def find_device():
        if BLE_DEVICE_ADDRESS:
            return BLE_DEVICE_ADDRESS
        devices = await BleakScanner.discover()
        for d in devices:
            if BLE_DEVICE_NAME and (d.name or "") == BLE_DEVICE_NAME:
                return d.address
        return None

    async def run():
        while True:
            try:
                addr = await find_device()
                if not addr:
                    print("[ble] Device not found. Scanning again in 5s...")
                    await asyncio.sleep(5)
                    continue
                print(f"[ble] Connecting to {addr}...")
                async with BleakClient(addr) as cl:
                    if BLE_CHAR_UUID:
                        def on_notify(_, data: bytes):
                            try:
                                msg = data.decode("utf-8", errors="ignore").strip()
                            except Exception:
                                msg = ""
                            if msg:
                                # print("[ble]", msg)
                                if msg == "EVENT:LEAVING":
                                    broadcast({"type": "LEAVING", "ts": time.time()})

                        await cl.start_notify(BLE_CHAR_UUID, on_notify)
                        print("[ble] Subscribed to notifications.")
                        # Keep connection
                        while True:
                            await asyncio.sleep(1)
                    else:
                        print("[ble] BLE_CHAR_UUID not set; cannot subscribe.")
                        await asyncio.sleep(10)
            except Exception as e:
                print("[ble] Error:", e)
                await asyncio.sleep(3)

    try:
        import asyncio
        asyncio.run(run())
    except Exception as e:
        print("[ble] Loop error:", e)

@app.on_event("startup")
def startup():
    threading.Thread(target=serial_worker, daemon=True).start()
    if ENABLE_BLE:
        print("[ble] BLE enabled. Starting BLE worker...")
        threading.Thread(target=ble_worker, daemon=True).start()

@app.get("/", response_class=HTMLResponse)
def index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/events/stream")
async def sse_stream():
    box: List[Dict[str, Any]] = []
    subscribers.append(box)

    async def gen():
        try:
            while True:
                if box:
                    ev = box.pop(0)
                    yield f"data: {__import__('json').dumps(ev)}\n\n"
                else:
                    yield ":\n\n"
                await __import__("asyncio").sleep(0.25)
        finally:
            if box in subscribers:
                subscribers.remove(box)

    return StreamingResponse(gen(), media_type="text/event-stream")

def _get_embedding(text: str) -> List[float]:
    try:
        if client and hasattr(client, "embeddings"):
            r = client.embeddings.create(model=EMBEDDINGS_MODEL, input=text)
            return list(r.data[0].embedding)
    except Exception as e:
        print("[embed] client.embeddings.create failed:", e)
    try:
        if hasattr(openai_mod, "Embedding"):
            r = openai_mod.Embedding.create(model=EMBEDDINGS_MODEL, input=text)
            return list(r["data"][0]["embedding"])  # legacy dict
    except Exception as e:
        print("[embed] openai.Embedding.create failed:", e)
    return []

def _cosine(a: List[float], b: List[float]) -> float:
    import math
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x*y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(y*y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)

_candidate_embeds: Dict[str, List[float]] = {}

def _build_candidate_embeddings() -> None:
    if _candidate_embeds:
        return
    # Candidate phrases for each destination
    SYNONYMS = {
        "gym": ["gym", "workout", "fitness"],
        "class": ["class", "lecture", "course", "classroom"],
        "campus": ["campus", "university", "college", "school"],
        "work": ["work", "office", "job", "workplace", "company"],
        "grocery": ["grocery", "groceries", "supermarket", "market"],
        "store": ["store", "shop", "shopping", "market"],
    }
    phrases: List[str] = []
    for key in DEST_ITEMS.keys():
        phrases.append(key)
        for s in SYNONYMS.get(key, []):
            phrases.append(s)
    # Dedup
    phrases = dedup(phrases)
    # Build embeddings
    for p in phrases:
        emb = _get_embedding(p)
        if emb:
            _candidate_embeds[p] = emb

def _choose_by_embeddings(text: str) -> str:
    if client is None:
        return ""
    _build_candidate_embeddings()
    q = _get_embedding(text)
    if not q:
        return ""
    best_key, best_score = "", 0.0
    for key in DEST_ITEMS.keys():
        # Compare against the key itself and its synonyms
        pool = [key] + [p for p in _candidate_embeds.keys() if p != key and p in _candidate_embeds and p in (key,)]
        # Above line mistakenly limits pool; build proper pool:
    # Rebuild pool properly
    SYNONYMS = {
        "gym": ["gym", "workout", "fitness"],
        "class": ["class", "lecture", "course", "classroom"],
        "campus": ["campus", "university", "college", "school"],
        "work": ["work", "office", "job", "workplace", "company"],
        "grocery": ["grocery", "groceries", "supermarket", "market"],
        "store": ["store", "shop", "shopping", "market"],
    }
    best_key, best_score = "", 0.0
    for key, syns in SYNONYMS.items():
        pool = [key] + syns
        score = 0.0
        for p in pool:
            emb = _candidate_embeds.get(p) or []
            if emb:
                score = max(score, _cosine(q, emb))
        if score > best_score:
            best_key, best_score = key, score
    # Threshold to avoid random matches
    if best_score >= 0.60:
        return best_key
    return ""

def normalize_destination(text: str) -> str:
    t = (text or "").lower().strip()
    import re
    from difflib import SequenceMatcher

    # Try embeddings-based selection first (maps "jim" -> "gym")
    try:
        dest = _choose_by_embeddings(t)
        if dest:
            return dest
    except Exception as e:
        print("[embed] destination selection failed:", e)

    # Tokenize simple words
    words = re.findall(r"[a-zA-Z]+", t)

    SYNONYMS = {
        "gym": ["gym", "workout", "fitness", "jim", "weightroom"],
        "class": ["class", "lecture", "course", "classroom"],
        "campus": ["campus", "university", "college", "school"],
        "work": ["work", "office", "job", "workplace", "company"],
        "grocery": ["grocery", "groceries", "supermarket", "market", "grocerystore"],
        "store": ["store", "shop", "shopping", "market"],
    }

    # 1) Direct substring match
    for key in DEST_ITEMS.keys():
        if key in t:
            return key

    # 2) Synonym exact word match
    for key, syns in SYNONYMS.items():
        for s in syns:
            if s in words or s.replace(" ", "") in t:
                return key

    # 3) Fuzzy match per word against destination keys
    best_key, best_score = "", 0.0
    for w in words:
        for key in DEST_ITEMS.keys():
            score = SequenceMatcher(None, w, key).ratio()
            if score > best_score:
                best_key, best_score = key, score
    if best_score >= 0.75:
        return best_key

    # Fallback: last word
    return words[-1] if words else ""

def dedup(items: List[str]) -> List[str]:
    out, seen = [], set()
    for it in items:
        s = str(it).strip()
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out

def items_from_builtin(dest_key: str) -> List[str]:
    extras = DEST_ITEMS.get(dest_key, [])
    return dedup(BASE_ESSENTIALS + extras)
def sanitize_items(items: List[str]) -> List[str]:
    out: List[str] = []
    for it in items:
        s = str(it).strip()
        if not s:
            continue
        # Drop sentences or replies
        if any(c in s for c in ".!?"):
            continue
        if len(s.split()) > 4:
            continue
        out.append(s)
    # Always include essentials and cap length
    out = dedup(BASE_ESSENTIALS + out)
    return out[:10]

def items_from_llm(transcript: str) -> List[str]:
    if client is None:
        return []
    # Build a strict prompt — user perspective, JSON-only
    prompt = f"""
Return ONLY valid JSON: {{"items": [string,...]}}.

I am going to "{transcript}".
List the items I would need to bring.

Rules:
- Keep it short and practical (5–10 items).
- ALWAYS include: keys, wallet, phone, ID (unless clearly irrelevant).
- Use concise item nouns only; NO sentences or explanations.
"""

    text: str = ""
    # Preferred: Responses API
    try:
        if hasattr(client, "responses"):
            resp = client.responses.create(
                model=LLM_MODEL,
                input=prompt,
                temperature=0,
                response_format={"type": "json_object"}
            )
            text = getattr(resp, "output_text", "").strip() or str(resp)
    except Exception as e:
        print("[llm] responses.create failed:", e)

    # Fallback: Chat Completions (new SDK style)
    if not text:
        try:
            if hasattr(client, "chat") and hasattr(client.chat, "completions"):
                comp = client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=[
                        {"role": "system", "content": "Return ONLY JSON in the format {\"items\":[string,...]}"},
                        {"role": "user", "content": transcript},
                    ],
                    temperature=0,
                )
                text = (comp.choices[0].message.content or "").strip()
        except Exception as e:
            print("[llm] chat.completions.create failed:", e)

    # Fallback: ChatCompletion (legacy SDK)
    if not text:
        try:
            if hasattr(openai_mod, "ChatCompletion"):
                comp = openai_mod.ChatCompletion.create(
                    model=LLM_MODEL,
                    messages=[
                        {"role": "system", "content": "Return ONLY JSON in the format {\"items\":[string,...]}"},
                        {"role": "user", "content": transcript},
                    ],
                    temperature=0,
                )
                # Legacy returns dict
                text = str(comp["choices"][0]["message"]["content"]).strip()
        except Exception as e:
            print("[llm] ChatCompletion.create failed:", e)

    import json
    try:
        data = json.loads(text)
        items = data.get("items", [])
        if not isinstance(items, list):
            return []
        return sanitize_items([str(x) for x in items])
    except Exception:
        return []

def transcribe_audio(file_obj) -> str:
    # Try modern SDK
    try:
        if client and hasattr(client, "audio") and hasattr(client.audio, "transcriptions"):
            stt = client.audio.transcriptions.create(model=STT_MODEL, file=file_obj)
            return getattr(stt, "text", None) or (stt.get("text") if isinstance(stt, dict) else "") or ""
    except Exception as e:
        print("[stt] client.audio.transcriptions.create failed:", e)

    # Try module-level modern SDK
    try:
        if hasattr(openai_mod, "audio") and hasattr(openai_mod.audio, "transcriptions"):
            stt = openai_mod.audio.transcriptions.create(model=STT_MODEL, file=file_obj)
            return getattr(stt, "text", None) or (stt.get("text") if isinstance(stt, dict) else "") or ""
    except Exception as e:
        print("[stt] openai.audio.transcriptions.create failed:", e)

    # Legacy Whisper endpoint
    try:
        if hasattr(openai_mod, "Audio") and hasattr(openai_mod.Audio, "transcribe"):
            stt = openai_mod.Audio.transcribe("whisper-1", file_obj)
            return getattr(stt, "text", None) or (stt.get("text") if isinstance(stt, dict) else "") or ""
    except Exception as e:
        print("[stt] openai.Audio.transcribe failed:", e)

    return ""

@app.post("/audio_suggest")
async def audio_suggest(audio: UploadFile = File(...)):
    """
    Receives recorded audio from browser.
    Transcribes it, applies voice commands, returns items.
    """
    global last_items, last_transcript

    import io

    raw = await audio.read()
    f = io.BytesIO(raw)
    f.name = audio.filename or "clip.webm"

    # Speech-to-text requires OpenAI client and API key
    if client is None:
        return {"transcript": "", "items": [], "mode": "error", "message": "OPENAI_API_KEY is not set. Set it and restart the server."}

    transcript = transcribe_audio(f)
    transcript = (transcript or "").strip()
    if not transcript:
        return {"transcript": "", "items": [], "mode": "error", "message": "No transcript"}

    t = transcript.lower()

    # Voice commands
    if "cancel" in t or "stop" in t:
        last_transcript = transcript
        return {"transcript": transcript, "items": [], "mode": "command", "message": "Cancelled"}

    if "repeat" in t:
        return {"transcript": transcript, "items": last_items, "mode": "command", "message": "Repeat"}

    # Normal destination flow
    dest_key = normalize_destination(transcript)
    items = items_from_builtin(dest_key)

    # Prefer LLM-generated items when available
    if client is not None:
        llm_items = items_from_llm(transcript)
        if llm_items:
            items = dedup(llm_items)

    last_items = items
    last_transcript = transcript
    return {"transcript": transcript, "items": items, "mode": "result", "message": ""}
