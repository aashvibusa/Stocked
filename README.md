# Stocked

**Stocked is a voice AI agent that calls local pharmacies to check whether a prescription medication is in stock.**

Built with [Pipecat](https://pipecat.ai), [NVIDIA Nemotron](https://huggingface.co/nvidia), [Gradium](https://gradium.ai), [Twilio](https://twilio.com), and [Cekura]([https://cekura.com](https://www.cekura.ai)).

Stocked was inspired by a family member’s frustrating experience of spending hours calling multiple pharmacies and driving around just to find where their prescription was in stock. They expressed how much of an extra burden this added to their lives. We realized that a lot of people face this stressful hurdle for medication that they need to thrive.  So we created Stocked to completely automate the pharmacy-checking process. Our mission is to eliminate the tedious phone calls so that people can get their essential medications reliably and effortlessly. Stocked calls multiple pharmacies concurrently to expidite the process, and provides the patient with a text letting them know where they can find their presrcpition.  We built this project from scratch specifically for this hackathon.


## How it works

1. You call the Stocked phone number: (360) 302-4376
2. **Arya** (our voice agent) picks up, asks your name, what medication you need, the dosage, and your area
3. Arya hangs up and immediately calls pharmacies near you in parallel
4. Arya asks each pharmacy: *"Hi, this is Arya calling from Stocked on behalf of [your name]. Do you have [medication] [dosage] available for pickup?"*
5. You get a text with the results:
   ```
   Hi [your name], we checked 3 pharmacies for Amoxicillin 500mg.
     CVS Pharmacy: IN STOCK ($12.99)
     Walgreens: OUT OF STOCK
     Rite Aid: OUT OF STOCK
   - Stocked
   ```

## Video Link

https://youtu.be/ppo6F4hg9AI

## Tech stack

| Component | Service |
|-----------|---------|
| **STT** | NVIDIA Nemotron Speech Streaming (Parakeet 0.6B) |
| **LLM** | NVIDIA Nemotron-3-Super-120B via vLLM |
| **TTS** | Gradium |
| **Orchestration** | Pipecat |
| **Phone and Text** | Twilio |


### Feedback

- Cekura was very interactve, but a bit difficult to set up with our workload for calling multiple agents at once and combining with Twilio's free trial tier as it required physically pressing a key to execute code.
- Overall, the NVIDIA models were very good at interacting with a user, however they did have some trouble understanding non-traditional names and frequently picked up background noise.
- Twilio was very intuitive to set up for the most part, though it would be nice to have a more streamlined process for SMS messaging.
- Pipecat was easy to use and integrated seamlessly with our workflow. It made it easy to pass around transcript data between services.



# Additional Set Up Info 
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

This is to simulate the inventory of various pharamacies for demonstration purposes. 

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
