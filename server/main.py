"""Stocked — Main FastAPI server.

Handles:
1. Inbound Twilio webhook (/ws/intake) for user intake calls
2. POST /api/search — triggers parallel outbound pharmacy calls
3. Outbound Twilio calls route to MOCK_PHARMACY_NUMBER (mock bot or your phone)
4. Dashboard (/dashboard) for live call status
5. API endpoints for call log data

HOW OUTBOUND CALLS WORK:
  All outbound calls go to a single Twilio number (MOCK_PHARMACY_NUMBER).
  That number's TwiML Bin routes the call to /ws/mock on this server,
  where mock_pharmacies.py answers as a simulated pharmacist.

  For DEMO MODE: set DEMO_PHONE_NUMBER in .env to YOUR phone number.
  The outbound calls will ring your phone so YOU can play the pharmacist.
"""

import asyncio
import os

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse
from loguru import logger
from pydantic import BaseModel
from twilio.rest import Client as TwilioClient
from twilio.twiml.voice_response import Connect, Stream, VoiceResponse

import call_log
from pharmacy_data import get_pharmacies_for_area
from sms_helper import send_summary_sms

load_dotenv(override=True)

app = FastAPI(title="Stocked")


# ─────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    request_id: str
    caller_phone: str
    caller_name: str = "Friend"
    medication: str
    dosage: str
    location: str


# ─────────────────────────────────────────────────────────────
# 1. Inbound intake WebSocket (Twilio -> bot_user_intake)
# ─────────────────────────────────────────────────────────────

@app.websocket("/ws/intake")
async def ws_intake(websocket: WebSocket):
    """Twilio Media Stream WebSocket for inbound user intake calls."""
    from bot_user_intake import bot
    from pipecat.runner.types import WebSocketRunnerArguments

    await websocket.accept()
    logger.info("Intake WebSocket connected")
    try:
        runner_args = WebSocketRunnerArguments(websocket=websocket)
        await bot(runner_args)
    except Exception as e:
        logger.error(f"Intake WebSocket error: {e}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
# 2. Pharmacy search trigger (called by intake bot)
# ─────────────────────────────────────────────────────────────

@app.post("/api/search")
async def trigger_search(req: SearchRequest) -> JSONResponse:
    """Start parallel outbound calls to pharmacies."""
    logger.info(f"Search request: {req.medication} {req.dosage} in {req.location}")

    pharmacies = get_pharmacies_for_area(req.location, limit=3)

    # Pre-populate call log with "calling" status so dashboard shows them right away
    await call_log.create_request(
        request_id=req.request_id,
        caller_phone=req.caller_phone,
        medication=req.medication,
        dosage=req.dosage,
        location=req.location,
        pharmacy_names=[{"name": p["name"], "address": p["address"]} for p in pharmacies],
    )
    logger.info(f"Calling {len(pharmacies)} pharmacies: {[p['name'] for p in pharmacies]}")

    # Launch parallel outbound calls in background
    asyncio.create_task(_run_parallel_calls(req, pharmacies))

    return JSONResponse({
        "status": "search_started",
        "request_id": req.request_id,
        "pharmacies": [{"name": p["name"], "address": p["address"]} for p in pharmacies],
    })


async def _run_parallel_calls(req: SearchRequest, pharmacies: list[dict]):
    """Make outbound Twilio calls to pharmacies.

    DEMO MODE (DEMO_PHONE_NUMBER set): Calls YOUR phone ONCE with the first
    pharmacy. The other two are marked as simulated results so you only get
    one phone call to answer during a live demo.

    MOCK MODE (MOCK_PHARMACY_NUMBER set): All 3 calls run in parallel to
    the mock bot — fully automated.
    """
    is_demo = bool(os.getenv("DEMO_PHONE_NUMBER"))

    if is_demo:
        # Only call once — you answer as the first pharmacy
        demo_pharmacy = pharmacies[0]
        logger.info(f"DEMO MODE: calling you once as {demo_pharmacy['name']}")

        try:
            await _make_outbound_call(req, demo_pharmacy)
        except Exception as e:
            logger.error(f"Demo call failed: {e}")
            await call_log.update_pharmacy_call(
                request_id=req.request_id,
                pharmacy_name=demo_pharmacy["name"],
                pharmacy_address=demo_pharmacy["address"],
                status="failed", in_stock=None, price=None,
                transcript=f"Error: {e}",
            )

        # Simulate the other 2 pharmacies with fake results
        for pharmacy in pharmacies[1:]:
            import random
            in_stock = random.choice([True, False])
            price = f"{random.uniform(8, 45):.2f}" if in_stock else None
            await call_log.update_pharmacy_call(
                request_id=req.request_id,
                pharmacy_name=pharmacy["name"],
                pharmacy_address=pharmacy["address"],
                status="completed", in_stock=in_stock, price=price,
                transcript="[simulated for demo]",
            )
    else:
        # MOCK MODE: all 3 in parallel
        tasks = [_make_outbound_call(req, pharmacy) for pharmacy in pharmacies]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Call to {pharmacies[i]['name']} failed: {result}")
                await call_log.update_pharmacy_call(
                    request_id=req.request_id,
                    pharmacy_name=pharmacies[i]["name"],
                    pharmacy_address=pharmacies[i]["address"],
                    status="failed", in_stock=None, price=None,
                    transcript=f"Error: {result}",
                )

    # Wait for live call results to come in, then send SMS
    for _ in range(60):
        await asyncio.sleep(2)
        request_data = await call_log.get_request(req.request_id)
        if request_data and request_data["status"] == "done":
            break

    request_data = await call_log.get_request(req.request_id)
    if request_data:
        send_summary_sms(
            caller_phone=req.caller_phone,
            caller_name=req.caller_name,
            medication=req.medication,
            dosage=req.dosage,
            pharmacy_results=request_data["pharmacy_calls"],
        )


async def _make_outbound_call(req: SearchRequest, pharmacy: dict) -> dict:
    """Initiate a single outbound Twilio call.

    The call goes to DEMO_PHONE_NUMBER (your phone) or MOCK_PHARMACY_NUMBER
    (routed back to the mock bot). Never to a real pharmacy.
    """
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_PHONE_NUMBER")
    server_url = os.getenv("LOCAL_SERVER_URL")

    # Where the call actually goes:
    # 1. DEMO mode — rings YOUR phone so you can role-play as the pharmacist
    # 2. MOCK mode — rings a second Twilio number routed to mock_pharmacies.py
    to_number = os.getenv("DEMO_PHONE_NUMBER") or os.getenv("MOCK_PHARMACY_NUMBER")

    if not all([account_sid, auth_token, from_number, server_url, to_number]):
        raise ValueError(
            "Missing config. Set TWILIO_* + LOCAL_SERVER_URL + "
            "(DEMO_PHONE_NUMBER or MOCK_PHARMACY_NUMBER) in .env"
        )

    client = TwilioClient(account_sid, auth_token)

    # TwiML URL passes metadata so the receiving end knows what's being asked
    twiml_url = (
        f"{server_url}/twiml/outbound"
        f"?medication={req.medication}"
        f"&dosage={req.dosage}"
        f"&pharmacy_name={pharmacy['name']}"
        f"&pharmacy_address={pharmacy['address']}"
        f"&request_id={req.request_id}"
        f"&caller_name={req.caller_name}"
    )

    call = client.calls.create(
        to=to_number,
        from_=from_number,
        url=twiml_url,
        method="POST",
    )

    logger.info(f"Outbound call to {pharmacy['name']} (via {to_number}): SID={call.sid}")
    return {"call_sid": call.sid, "pharmacy": pharmacy["name"]}


# ─────────────────────────────────────────────────────────────
# 3. Outbound call TwiML + WebSocket
# ─────────────────────────────────────────────────────────────

@app.post("/twiml/outbound")
async def twiml_outbound(request: Request) -> HTMLResponse:
    """Return TwiML that connects the outbound call to our WebSocket.

    When the call is answered (by mock bot or by you in demo mode),
    Twilio opens a media stream to /ws/outbound where the pharmacy
    caller Pipecat bot runs.
    """
    params = dict(request.query_params)
    server_url = os.getenv("LOCAL_SERVER_URL", "")
    ws_url = server_url.replace("https://", "wss://").replace("http://", "ws://")

    response = VoiceResponse()
    connect = Connect()
    stream = Stream(url=f"{ws_url}/ws/outbound")

    for key in ("medication", "dosage", "pharmacy_name", "pharmacy_address", "request_id", "caller_name"):
        if key in params:
            stream.parameter(name=key, value=params[key])

    connect.append(stream)
    response.append(connect)
    response.pause(length=60)

    return HTMLResponse(content=str(response), media_type="application/xml")


@app.websocket("/ws/outbound")
async def ws_outbound(websocket: WebSocket):
    """Twilio Media Stream WebSocket for outbound pharmacy calls."""
    from bot_pharmacy_caller import bot
    from pipecat.runner.types import WebSocketRunnerArguments

    await websocket.accept()
    logger.info("Outbound pharmacy WebSocket connected")
    try:
        runner_args = WebSocketRunnerArguments(websocket=websocket)
        await bot(runner_args)
    except Exception as e:
        logger.error(f"Outbound WebSocket error: {e}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
# 4. Mock pharmacy WebSocket (for automated testing)
# ─────────────────────────────────────────────────────────────

@app.post("/twiml/mock")
async def twiml_mock(request: Request) -> HTMLResponse:
    """TwiML for mock pharmacy — routes incoming call to mock bot.

    Configure MOCK_PHARMACY_NUMBER's TwiML Bin to POST here.
    The mock bot (helpful or grumpy persona) answers and role-plays.
    """
    params = dict(request.query_params)
    server_url = os.getenv("LOCAL_SERVER_URL", "")
    ws_url = server_url.replace("https://", "wss://").replace("http://", "ws://")

    response = VoiceResponse()
    connect = Connect()
    stream = Stream(url=f"{ws_url}/ws/mock")
    stream.parameter(name="persona", value=params.get("persona", "helpful"))
    stream.parameter(name="pharmacy_name", value=params.get("pharmacy_name", "the pharmacy"))
    connect.append(stream)
    response.append(connect)
    response.pause(length=60)

    return HTMLResponse(content=str(response), media_type="application/xml")


@app.websocket("/ws/mock")
async def ws_mock(websocket: WebSocket):
    """WebSocket for mock pharmacy bots (Cekura or automated testing)."""
    from mock_pharmacies import bot
    from pipecat.runner.types import WebSocketRunnerArguments

    await websocket.accept()
    logger.info("Mock pharmacy WebSocket connected")
    try:
        runner_args = WebSocketRunnerArguments(websocket=websocket)
        await bot(runner_args)
    except Exception as e:
        logger.error(f"Mock pharmacy WebSocket error: {e}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
# 5. Dashboard + API
# ─────────────────────────────────────────────────────────────

@app.get("/api/requests")
async def get_requests():
    """Return all search requests and their pharmacy call results."""
    return await call_log.get_all_requests()


@app.get("/api/requests/{request_id}")
async def get_request(request_id: str):
    data = await call_log.get_request(request_id)
    if not data:
        return JSONResponse({"error": "not found"}, status_code=404)
    return data


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Simple dashboard showing live call status."""
    return DASHBOARD_HTML


DASHBOARD_HTML = """<!DOCTYPE html>
<html>
<head>
  <title>Stocked - Dashboard</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: -apple-system, sans-serif; background: #0f172a; color: #e2e8f0; padding: 2rem; }
    h1 { font-size: 1.8rem; margin-bottom: 0.25rem; }
    h1 span { color: #38bdf8; }
    .subtitle { color: #64748b; font-size: 0.85rem; margin-bottom: 1.5rem; }
    .status-bar { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 1.5rem; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: #22c55e; animation: pulse 2s infinite; }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
    .request { background: #1e293b; border-radius: 10px; padding: 1.5rem; margin-bottom: 1.5rem;
               border: 1px solid #334155; }
    .request-header { display: flex; justify-content: space-between; align-items: center; }
    .request h2 { color: #f8fafc; font-size: 1.15rem; }
    .meta { color: #94a3b8; font-size: 0.8rem; margin: 0.4rem 0 1rem; }
    .pharmacy-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 0.75rem; }
    .call-card { background: #0f172a; border-radius: 8px; padding: 1rem; border: 1px solid #1e293b; }
    .call-card.active { border-color: #f59e0b; animation: ring 1.5s infinite; }
    @keyframes ring { 0%,100%{border-color:#f59e0b} 50%{border-color:#0f172a} }
    .call-card .pharmacy-name { font-weight: 600; font-size: 0.95rem; margin-bottom: 0.25rem; }
    .call-card .pharmacy-addr { color: #64748b; font-size: 0.75rem; margin-bottom: 0.5rem; }
    .badge { display: inline-block; padding: 2px 10px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; }
    .badge.in-stock { background: #22c55e; color: #052e16; }
    .badge.out { background: #ef4444; color: #fff; }
    .badge.searching { background: #f59e0b; color: #422006; }
    .badge.failed { background: #6b7280; color: #fff; }
    .badge.done { background: #22c55e; color: #052e16; }
    .transcript { margin-top: 0.75rem; background: #1e293b; border-radius: 6px; padding: 0.6rem 0.75rem;
                  font-size: 0.75rem; color: #94a3b8; max-height: 120px; overflow-y: auto;
                  font-family: 'SF Mono', Monaco, monospace; white-space: pre-wrap; }
    .transcript:empty { display: none; }
    .summary-sms { background: #1e3a5f; border-radius: 8px; padding: 1rem; margin-top: 1rem;
                   font-size: 0.85rem; border-left: 3px solid #38bdf8; }
    .summary-sms .label { color: #38bdf8; font-weight: 600; margin-bottom: 0.3rem; }
    .empty { color: #64748b; text-align: center; padding: 4rem 2rem; }
    .empty h3 { color: #94a3b8; margin-bottom: 0.5rem; }
    .pending-pills { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-top: 0.75rem; }
    .pending-pill { background: #334155; padding: 4px 10px; border-radius: 12px; font-size: 0.75rem; color: #94a3b8; }
    .pending-pill.calling { background: #422006; color: #f59e0b; }
  </style>
</head>
<body>
  <h1><span>Stocked</span></h1>
  <div class="subtitle">Real-time pharmacy availability search</div>
  <div class="status-bar"><div class="dot"></div><span style="color:#94a3b8;font-size:0.8rem">Live &mdash; auto-refreshing</span></div>
  <div id="content">
    <div class="empty">
      <h3>No search requests yet</h3>
      <p>Call your Twilio number or POST to /api/search to start.</p>
    </div>
  </div>
  <script>
    function statusBadge(r) {
      if (r.status === 'done') return '<span class="badge done">COMPLETE</span>';
      return '<span class="badge searching">SEARCHING</span>';
    }
    function callBadge(c) {
      if (c.status === 'calling') return '<span class="badge searching">CALLING...</span>';
      if (c.in_stock) return `<span class="badge in-stock">IN STOCK${c.price ? ' $'+c.price : ''}</span>`;
      if (c.status === 'failed') return '<span class="badge failed">UNREACHABLE</span>';
      return '<span class="badge out">OUT OF STOCK</span>';
    }
    function smsSummary(r) {
      if (r.status !== 'done') return '';
      const lines = r.pharmacy_calls.map(c => {
        if (c.in_stock) return `  ${c.pharmacy_name}: IN STOCK` + (c.price ? ` ($${c.price})` : '');
        if (c.status === 'failed') return `  ${c.pharmacy_name}: COULD NOT REACH`;
        return `  ${c.pharmacy_name}: OUT OF STOCK`;
      });
      return `<div class="summary-sms">
        <div class="label">SMS sent to caller</div>
        We checked ${r.pharmacy_calls.length} pharmacies for ${r.medication} ${r.dosage}:\\n${lines.join('\\n')}
      </div>`;
    }
    function pendingPharmacies(r) {
      if (r.status === 'done' || r.pharmacy_calls.length >= 3) return '';
      const called = new Set(r.pharmacy_calls.map(c => c.pharmacy_name));
      const total = 3;
      const remaining = total - r.pharmacy_calls.length;
      if (remaining <= 0) return '';
      let pills = '';
      for (let i = 0; i < remaining; i++) pills += '<span class="pending-pill calling">Calling...</span>';
      return `<div class="pending-pills">${pills}</div>`;
    }
    async function refresh() {
      try {
        const res = await fetch('/api/requests');
        const data = await res.json();
        const el = document.getElementById('content');
        if (!data.length) return;
        el.innerHTML = data.reverse().map(r => `
          <div class="request">
            <div class="request-header">
              <h2>${r.medication} ${r.dosage}</h2>
              ${statusBadge(r)}
            </div>
            <div class="meta">${r.request_id} &middot; ${r.location} &middot; ${r.created_at}</div>
            <div class="pharmacy-grid">
              ${r.pharmacy_calls.map(c => `
                <div class="call-card${c.status === 'calling' ? ' active' : ''}">
                  <div class="pharmacy-name">${c.pharmacy_name}</div>
                  <div class="pharmacy-addr">${c.pharmacy_address || ''}</div>
                  ${callBadge(c)}
                  <div class="transcript">${c.transcript || ''}</div>
                </div>
              `).join('')}
            </div>
            ${pendingPharmacies(r)}
            ${smsSummary(r)}
          </div>
        `).join('');
      } catch(e) { console.error(e); }
    }
    refresh();
    setInterval(refresh, 2000);
  </script>
</body>
</html>"""


@app.get("/health")
async def health():
    return {"status": "ok", "service": "pharmafetch-ai"}


if __name__ == "__main__":
    port = int(os.getenv("PORT", "7860"))
    logger.info(f"Starting Stocked on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
