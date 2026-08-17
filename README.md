# Northstar Homes — AI Sales Agent

Conversational AI sales agent for the fictional project **Northstar One**
(Sector 79, Gurugram · 2 BHK ₹1.35 Cr+ · 3 BHK ₹1.75 Cr+). One system prompt
drives it across **chat and voice**, in **English / Hindi / Hinglish**.

## Files
| File | What it is |
|---|---|
| `prompt.py` | **The core deliverable** — the system prompt + the analytics prompt |
| `app.py` | FastAPI backend: `/chat`, `/end` — session memory, booking sim, analytics |
| `static/index.html` | Single-file chat UI |
| `test_scenarios.py` | Offline unit checks + live scenario runner (input/expected/actual) |

## Run
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then paste your free key from aistudio.google.com
uvicorn app:app --reload
```
Open http://localhost:8000

## Key assumptions
- **Only the given facts are ground truth** — project, location, 2/3 BHK, and the two starting prices. The agent is prompt-forbidden from inventing anything else (amenities, possession, discounts, availability, EMI, RERA…).
- **One prompt for chat and voice** — so the prompt bans markdown, emojis, links, and words like "click/type", and keeps turns short and spoken-friendly. No separate voice prompt.
- **Site-visit hours are 10 AM–7 PM, any day.** Booking is *simulated*; there's no real calendar/CRM.
- **Language is detected per turn** and mirrored (English / Hindi / Hinglish).
- **A session = one browser tab** (`session_id` from `crypto.randomUUID()`); memory lives in-process.

## Known limitations
- **In-memory sessions** — lost on server restart, and won't work across multiple workers. Swap `SESSIONS`/`BOOKINGS` for Redis/DB to persist.
- **Free Gemini tier = 5 requests/min.** `_generate()` retries once on a 429 (waits out the minute), so a busy multi-turn chat can stall ~60s. A paid tier removes this.
- **Booking is a stub** — validates hours and returns a fake `NH-` id; it doesn't write to a real calendar.
- **Language mirroring can slip** on emotionally-toned messages (observed: one English complaint answered in Hindi). See `TEST_RESULTS.md`.
- **Booking relies on the model emitting a JSON action.** Parsing is defensive (regex + validation), but a badly-formatted model turn would just be treated as normal text.

## AI tools used
- **Google Gemini** (`gemini-2.5-flash`) — the conversational + analytics model.

## How it works
- **Memory** — each `session_id` keeps its full turn history (`SESSIONS`), replayed to Gemini every turn.
- **Booking** — when the agent has name, phone, date, time and the customer confirms, it emits a one-line JSON action. The backend runs `simulate_booking()` (valid 10 AM–7 PM), feeds the result back, and the agent replies naturally. Out-of-hours = deterministic failure the agent recovers from.
- **Analytics** — `POST /end` sends the transcript to a second Gemini call that returns structured lead data (budget, interest, configuration, site-visit status, follow-up, objections, escalation, opt-out, lead score…). The tracked booking flag overrides the model for site-visit status.
- **Grounding** — the prompt hard-limits the agent to the given facts; anything else → "I don't have that" + human/site-visit offer. No invented prices, discounts, or availability.
- **Provider-agnostic** — only `app.py`'s two Gemini helpers touch the SDK; swap them for Claude/OpenAI without touching the prompt.
