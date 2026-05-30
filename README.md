# Stocked

**Voice AI agent that calls pharmacies to check medication availability.**

Built for the YC Voice Agents Hackathon with [Pipecat](https://pipecat.ai), [NVIDIA Nemotron](https://huggingface.co/nvidia), [Twilio](https://twilio.com), and [Cekura](https://cekura.com).

## How it works

1. You call the Stocked phone number: (360) 302-4376
2. **Arya** (our voice agent) picks up, asks your name, what medication you need, the dosage, and your area
3. Arya hangs up and immediately calls pharmacies near you in parallel
4. Arya asks each pharmacy: *"Hi, this is Arya calling from Stocked on behalf of [your name]. Do you have [medication] [dosage] available for pickup?"*
5. You get a text with the results:
   ```
   Hi Siri, we checked 3 pharmacies for Amoxicillin 500mg.
     CVS Pharmacy: IN STOCK ($12.99)
     Walgreens: OUT OF STOCK
     Rite Aid: OUT OF STOCK
   - Stocked
   ```

## Tech stack

| Component | Service |
|-----------|---------|
| **STT** | NVIDIA Nemotron Speech Streaming (Parakeet 0.6B) |
| **LLM** | NVIDIA Nemotron-3-Super-120B via vLLM |
| **TTS** | Gradium |
| **Orchestration** | Pipecat |
| **Telephony** | Twilio |
| **Testing** | Cekura |

**Gradium** is a TTS (text-to-speech) provider — it converts Arya's text responses into spoken audio. **Pipecat** is the orchestration framework that wires STT -> LLM -> TTS into a real-time voice pipeline. You need both: Pipecat runs the pipeline, Gradium provides one of the services in it.

## Medication database

The mock pharmacies pull from `medication_db.py`. Each pharmacy has different stock:

| Medication | Dosage | Form | Qty | Price Range |
|-----------|--------|------|-----|-------------|
| Amoxicillin | 250mg, 500mg | capsule | 30 | $4-13 |
| Lisinopril | 10mg, 20mg | tablet | 30 | $4-18 |
| Metformin | 500mg, 850mg | tablet | 60 | $4-15 |
| Atorvastatin | 20mg, 40mg | tablet | 30 | $9-30 |
| Omeprazole | 20mg | capsule | 30 | $8-22 |
| Amlodipine | 5mg, 10mg | tablet | 30 | $4-15 |
| Levothyroxine | 50mcg, 100mcg | tablet | 30 | $4-25 |
| Azithromycin | 250mg | tablet | 6 | $8-18 |
| Ciprofloxacin | 500mg | tablet | 20 | $6-20 |
| Prednisone | 10mg | tablet | 21 | $4-10 |
| Ibuprofen | 800mg | tablet | 30 | $4-12 |
| Gabapentin | 300mg | capsule | 90 | $10-30 |
| Hydrochlorothiazide | 25mg | tablet | 30 | $4-10 |
| Sertraline | 50mg | tablet | 30 | $4-15 |

**Pharmacy inventory varies.** CVS has 11 medications, Rite Aid only has 4, Costco has everything. See `medication_db.py` for full details.

## Example call script

**You call Stocked:**
> *"Hi Arya, my name is Siri. Can you check if pharmacies near me in San Francisco have Amoxicillin 500mg?"*

**Arya confirms:**
> *"Hey Siri. So that's Amoxicillin, 500 milligram capsules, in San Francisco — right?"*

**You:** *"Yes"*

**Arya:** *"I'm on it, Siri. I'll call a few pharmacies near you right now and text you what I find."*

**Then Arya calls the pharmacy:**
> *"Hi, this is Arya calling from Stocked on behalf of Siri. I'm checking if you have Amoxicillin 500 milligram capsules available for pickup?"*

**Pharmacy:** *"Yes, we have that. For a thirty-day supply the cash price is about twelve ninety-nine."*

## Setup

### Prerequisites
- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)
- Twilio account with a phone number
- Gradium API key ([gradium.ai](https://gradium.ai))

### Install

```bash
cd server
cp .env.example .env
# Fill in your API keys in .env
uv sync
```

### Configure .env

```bash
# Twilio credentials
TWILIO_ACCOUNT_SID=ACxxxxx
TWILIO_AUTH_TOKEN=xxxxx
TWILIO_PHONE_NUMBER=+14155550100    # Your Twilio number

# DEMO MODE: Arya calls YOUR phone (you play the pharmacist)
DEMO_PHONE_NUMBER=+14155559999      # Your real phone

# MOCK MODE: Arya calls a 2nd Twilio number (mock bot answers)
# MOCK_PHARMACY_NUMBER=+14155550200

# Gradium TTS
GRADIUM_API_KEY=xxxxx

# NVIDIA (pre-configured for hackathon)
NVIDIA_ASR_URL=ws://44.241.251.184:8080
NEMOTRON_LLM_URL=http://nemotron-fleet-alb-1322439314.us-west-2.elb.amazonaws.com/v1
NEMOTRON_LLM_MODEL=nvidia/nemotron-3-super

# ngrok URL
LOCAL_SERVER_URL=https://abc123.ngrok.io
ENV=local
```

### Run

```bash
# Terminal 1: start ngrok
ngrok http 7860

# Terminal 2: start the server
cd server
uv run main.py
```

### Configure Twilio

**Inbound number** (people call this): Set voice webhook to a TwiML Bin:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="wss://YOUR-NGROK.ngrok.io/ws/intake"/>
  </Connect>
</Response>
```

**Mock pharmacy number** (optional, for mock mode): Set voice webhook to a TwiML Bin:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="wss://YOUR-NGROK.ngrok.io/ws/mock"/>
  </Connect>
</Response>
```

### Dashboard

Open `http://localhost:7860/dashboard` to see live call status, pharmacy results, and transcripts in real time.

### Test via API

```bash
curl -X POST http://localhost:7860/api/search \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "test1",
    "caller_phone": "+14155559999",
    "caller_name": "Siri",
    "medication": "Amoxicillin",
    "dosage": "500mg",
    "location": "SF"
  }'
```

### Test via WebRTC (no Twilio needed)

```bash
cd server
uv run bot_user_intake.py
# Open http://localhost:7860 and click Connect
```

## Cekura testing

```bash
# Install Cekura skills in Claude Code
/plugin marketplace add cekura-ai/cekura-skills
/plugin install cekura@cekura-skills

# Run end-to-end test
/cekura-report
```

Select **Pipecat** as the provider. Cekura runs automated voice conversations against Arya and the mock pharmacies, scores the transcripts, and reports failures.

## File structure

```
server/
├── main.py                  # FastAPI server — orchestrates everything
├── bot_user_intake.py       # Arya inbound: collects name, med, dosage, location
├── bot_pharmacy_caller.py   # Arya outbound: calls pharmacies on behalf of user
├── mock_pharmacies.py       # Mock pharmacy bots (helpful + grumpy personas)
├── medication_db.py         # Drug catalog + per-pharmacy inventory
├── pharmacy_data.py         # SF Bay Area pharmacy directory (16 locations)
├── call_log.py              # In-memory call tracking for dashboard + SMS
├── sms_helper.py            # Twilio SMS for sending results
├── nemotron_llm.py          # NVIDIA Nemotron LLM wrapper (TTFB metrics)
├── nvidia_stt.py            # NVIDIA Parakeet STT service
├── pyproject.toml           # uv package definitions
└── .env.example             # All required env vars
```
