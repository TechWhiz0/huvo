import json
import os
import re
import time
import uuid
from datetime import datetime, time as dtime

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from prompt import SYSTEM_PROMPT, ANALYTICS_PROMPT, VISIT_OPEN_HOUR, VISIT_CLOSE_HOUR

load_dotenv()
MODEL = "gemini-2.5-flash"


SESSIONS: dict[str, list] = {}  
BOOKINGS: dict[str, dict] = {}  

app = FastAPI(title="Northstar Homes Bot")


def _generate(system_instruction: str, contents: list, temperature: float) -> str:
    from google import genai
    from google.genai import types
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set — copy .env.example to .env")
    client = genai.Client(api_key=key)
    cfg = types.GenerateContentConfig(
        system_instruction=system_instruction, temperature=temperature
    )
    for attempt in range(3):
        try:
            resp = client.models.generate_content(
                model=MODEL, contents=contents, config=cfg
            )
            return (resp.text or "").strip()
        except Exception as e:  # ponytail: free tier is 5 req/min — on 429 wait
            if "429" in str(e) and attempt < 2:  # out the minute window and retry
                time.sleep(60)
                continue
            raise
    return ""


def _gemini(contents: list) -> str:
    return _generate(SYSTEM_PROMPT, contents, 0.7)


def _turn(role: str, text: str) -> dict:
    return {"role": role, "parts": [{"text": text}]}


def simulate_booking(date: str, time_str: str):
    """Return (ok, booking_id_or_reason). Fails outside 10 AM-7 PM so the
    failure path is deterministic and demoable."""
    try:
        t = datetime.strptime(time_str.strip(), "%H:%M").time()
    except ValueError:
        return False, "could not read the time (need HH:MM)"
    if not (dtime(VISIT_OPEN_HOUR, 0) <= t <= dtime(VISIT_CLOSE_HOUR, 0)):
        return False, "that time is outside our visiting hours (10 AM to 7 PM)"
    return True, "NH-" + uuid.uuid4().hex[:6].upper()


_ACTION_RE = re.compile(r'\{[^{}]*"action"\s*:\s*"book"[^{}]*\}', re.DOTALL)


def extract_action(text: str):
    m = _ACTION_RE.search(text)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return d if all(k in d for k in ("name", "phone", "date", "time")) else None



def handle_turn(session_id: str, message: str) -> dict:
    hist = SESSIONS.setdefault(session_id, [])
    hist.append(_turn("user", message))
    reply = _gemini(hist)

    action = extract_action(reply)
    booked = False
    if action:
        ok, result = simulate_booking(action["date"], action["time"])
        if ok:
            BOOKINGS[session_id] = {"id": result, **action}
            booked = True
            note = (f'[SYSTEM NOTE: Booking SUCCESS. Booking id {result} for '
                    f'{action["date"]} at {action["time"]}. Confirm this warmly '
                    f'to the customer and close politely.]')
        else:
            note = (f'[SYSTEM NOTE: Booking FAILED — {result}. Apologize briefly, '
                    f'explain simply, and offer an alternative time within 10 AM '
                    f'to 7 PM.]')
        hist.append(_turn("model", reply))   # the JSON action turn
        hist.append(_turn("user", note))     # tool result fed back
        reply = _gemini(hist)

    hist.append(_turn("model", reply))
    return {"reply": reply, "booked": booked, "session_id": session_id}


def _transcript(session_id: str) -> str:
    lines = []
    for turn in SESSIONS.get(session_id, []):
        text = turn["parts"][0]["text"]
        if text.startswith("[SYSTEM NOTE") or extract_action(text):
            continue  # hide internal plumbing from the analytics model
        who = "Customer" if turn["role"] == "user" else "Agent"
        lines.append(f"{who}: {text}")
    return "\n".join(lines)


def analyze(session_id: str) -> dict:
    transcript = _transcript(session_id)
    if not transcript:
        return {"error": "no conversation to analyze"}
    raw = _gemini_analytics(transcript)
    data = _parse_json(raw)
    if session_id in BOOKINGS:
        data["site_visit_status"] = "Booked"
        data["booking_id"] = BOOKINGS[session_id]["id"]
    return data


def _gemini_analytics(transcript: str) -> str:
    return _generate(ANALYTICS_PROMPT, [_turn("user", transcript)], 0)


def _parse_json(raw: str) -> dict:
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "could not parse analytics", "raw": raw}


class ChatIn(BaseModel):
    session_id: str
    message: str


class EndIn(BaseModel):
    session_id: str


@app.get("/")
def index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))


@app.post("/chat")
def chat(req: ChatIn):
    return handle_turn(req.session_id, req.message)


@app.post("/end")
def end(req: EndIn):
    return analyze(req.session_id)


def new_session() -> str:
    return uuid.uuid4().hex
