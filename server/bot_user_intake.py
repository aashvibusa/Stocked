"""Stocked — Arya inbound user-intake voice bot.

Greets the caller, collects their name, medication name, dosage, and location,
triggers the pharmacy search pipeline, tells the user they'll get a text,
and hangs up.

Pipeline: NVIDIA Nemotron Speech Streaming STT -> Nemotron-3-Super-120B LLM -> Gradium TTS
"""

import os
import uuid

import aiohttp
from dotenv import load_dotenv
from loguru import logger
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.turns.user_turn_strategies import UserTurnStrategies, VADUserTurnStartStrategy
from pipecat.turns.user_stop import SpeechTimeoutUserTurnStopStrategy
from pipecat.frames.frames import EndTaskFrame, FunctionCallResultProperties, LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.runner.types import (
    RunnerArguments,
    SmallWebRTCRunnerArguments,
    WebSocketRunnerArguments,
)
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.services.gradium.tts import GradiumTTSService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

from pipecat.workers.runner import WorkerRunner

from nemotron_llm import VLLMOpenAILLMService
from nvidia_stt import NVidiaWebSocketSTTService

load_dotenv(override=True)


async def get_call_info(call_sid: str) -> dict:
    """Fetch caller info from Twilio REST API."""
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    if not account_sid or not auth_token:
        return {}
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls/{call_sid}.json"
    try:
        auth = aiohttp.BasicAuth(account_sid, auth_token)
        async with aiohttp.ClientSession() as session:
            async with session.get(url, auth=auth) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
                return {"from_number": data.get("from"), "to_number": data.get("to")}
    except Exception as e:
        logger.error(f"Error fetching call info: {e}")
        return {}


async def run_bot(
    transport: BaseTransport,
    from_number: str | None = None,
    audio_in_sample_rate: int = 16000,
    audio_out_sample_rate: int = 24000,
):
    logger.info("Starting Arya intake bot")

    # ── Tool: trigger_pharmacy_search ────────────────────────
    async def trigger_pharmacy_search(
        params: FunctionCallParams,
        caller_name: str,
        medication: str,
        dosage: str,
        location: str,
    ) -> None:
        """Trigger the backend pharmacy search once all info is collected.

        Args:
            caller_name: The caller's first name.
            medication: Name of the medication (e.g. "Amoxicillin").
            dosage: Dosage and form (e.g. "500mg capsules", "10mg tablets").
            location: Area/city (e.g. "San Francisco", "SF Bay Area").
        """
        request_id = str(uuid.uuid4())[:8]
        caller_phone = from_number or "+10000000000"

        server_url = os.getenv("LOCAL_SERVER_URL", "http://localhost:7860")
        payload = {
            "request_id": request_id,
            "caller_phone": caller_phone,
            "caller_name": caller_name,
            "medication": medication,
            "dosage": dosage,
            "location": location,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{server_url}/api/search", json=payload, timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    result = await resp.json()
                    logger.info(f"Pharmacy search triggered: {result}")
        except Exception as e:
            logger.error(f"Failed to trigger pharmacy search: {e}")

        await params.result_callback({
            "ok": True,
            "request_id": request_id,
            "message": "Search started. The caller will receive a text with results.",
        })

    async def end_call(params: FunctionCallParams) -> None:
        """End the call after saying goodbye."""
        logger.info("end_call invoked — hanging up")
        await params.llm.push_frame(EndTaskFrame(), FrameDirection.UPSTREAM)
        await params.result_callback(
            {"ok": True}, properties=FunctionCallResultProperties(run_llm=False)
        )

    tool_functions = [trigger_pharmacy_search, end_call]
    tools = ToolsSchema(standard_tools=tool_functions)

    system_instruction = (
        "You are Arya, a friendly and efficient pharmacy assistant for Stocked. "
        "Stocked helps people find medications at local pharmacies by calling around "
        "for them. Your job is to collect FOUR pieces of information:\n"
        "1. The caller's first name\n"
        "2. Medication name (e.g. Amoxicillin, Lisinopril, Metformin)\n"
        "3. Dosage and form (e.g. 500mg capsules, 10mg tablets, 20mg)\n"
        "4. Location / area to search (e.g. San Francisco, SF Bay Area)\n\n"
        "Guidelines:\n"
        "- Greet: 'Hey, this is Arya from Stocked. I can help you find your "
        "medication at pharmacies near you. What's your name?'\n"
        "- Ask ONE question at a time. Don't stack questions.\n"
        "- After getting their name, ask what medication they need.\n"
        "- Then ask for the dosage if they didn't include it.\n"
        "- Then ask what area they're in.\n"
        "- Once you have all four, repeat them back: '[Name], just to confirm — "
        "you need [medication] [dosage] and you're looking in [location], right?'\n"
        "- After the caller confirms, call trigger_pharmacy_search with all four.\n"
        "- Then say: 'I'm on it, [name]. I'll call a few pharmacies near you "
        "right now and text you what I find.'\n"
        "- Say a quick goodbye and call end_call.\n"
        "- Keep responses to 1-2 short sentences. Sound natural, like a friend helping out.\n"
        "- Responses are spoken aloud. No bullet points, no emojis, no formatting.\n"
        "- Use contractions. Be warm but quick.\n"
    )

    stt = NVidiaWebSocketSTTService(
        url=os.getenv("NVIDIA_ASR_URL", "ws://44.241.251.184:8080"),
        sample_rate=16000,  # NVIDIA ASR requires 16kHz (Pipecat will resample from Twilio's 8kHz)
        strip_interim_prefix=True,
    )

    enable_thinking = os.getenv("NEMOTRON_ENABLE_THINKING", "false").lower() == "true"
    llm = VLLMOpenAILLMService(
        api_key=os.getenv("NEMOTRON_LLM_API_KEY", "EMPTY"),
        base_url=os.getenv("NEMOTRON_LLM_URL", "http://nemotron-fleet-alb-1322439314.us-west-2.elb.amazonaws.com/v1"),
        settings=VLLMOpenAILLMService.Settings(
            model=os.getenv("NEMOTRON_LLM_MODEL", "nvidia/nemotron-3-super"),
            system_instruction=system_instruction,
            extra={"extra_body": {"chat_template_kwargs": {"enable_thinking": enable_thinking}}},
        ),
    )

    tts = GradiumTTSService(
        api_key=os.environ["GRADIUM_API_KEY"],
        settings=GradiumTTSService.Settings(
            voice=os.getenv("GRADIUM_VOICE_ID", "Eu9iL_CYe8N-Gkx_"),
        ),
    )

    for fn in tool_functions:
        llm.register_direct_function(fn)

    context = LLMContext(tools=tools)
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(
                params=VADParams(confidence=0.5, stop_secs=0.8),
            ),
            user_turn_strategies=UserTurnStrategies(
                start=[VADUserTurnStartStrategy()],
                stop=[SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.8)],
            ),
        ),
    )

    pipeline = Pipeline([
        transport.input(),
        stt,
        user_aggregator,
        llm,
        tts,
        transport.output(),
        assistant_aggregator,
    ])

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
            audio_in_sample_rate=audio_in_sample_rate,
            audio_out_sample_rate=audio_out_sample_rate,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Arya intake: client connected")
        context.add_message({
            "role": "user",
            "content": "A caller just connected. Greet them as Arya.",
        })
        logger.info("Arya intake: queuing initial LLMRunFrame for greeting")
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Arya intake: client disconnected")
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    await runner.run()


async def bot(runner_args: RunnerArguments):
    """Entry point — handles both WebRTC (local dev) and Twilio (production)."""
    from_number: str | None = None
    transport_overrides: dict = {}

    krisp_filter = None
    if os.environ.get("ENV") != "local":
        try:
            from pipecat.audio.filters.krisp_viva_filter import KrispVivaFilter
            krisp_filter = KrispVivaFilter()
        except ImportError:
            pass

    match runner_args:
        case SmallWebRTCRunnerArguments():
            transport = SmallWebRTCTransport(
                webrtc_connection=runner_args.webrtc_connection,
                params=TransportParams(
                    audio_in_enabled=True,
                    audio_in_filter=krisp_filter,
                    audio_out_enabled=True,
                ),
            )
        case WebSocketRunnerArguments():
            transport_overrides["audio_in_sample_rate"] = 8000
            transport_overrides["audio_out_sample_rate"] = 8000
            _, call_data = await parse_telephony_websocket(runner_args.websocket)
            call_info = await get_call_info(call_data["call_id"])
            if call_info:
                from_number = call_info.get("from_number")
                logger.info(f"Intake call from: {from_number}")
            serializer = TwilioFrameSerializer(
                stream_sid=call_data["stream_id"],
                call_sid=call_data["call_id"],
                account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
                auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
            )
            transport = FastAPIWebsocketTransport(
                websocket=runner_args.websocket,
                params=FastAPIWebsocketParams(
                    audio_in_enabled=True,
                    audio_in_filter=krisp_filter,
                    audio_out_enabled=True,
                    add_wav_header=False,
                    serializer=serializer,
                ),
            )
        case _:
            logger.error(f"Unsupported runner arguments: {type(runner_args)}")
            return

    await run_bot(transport, from_number=from_number, **transport_overrides)


if __name__ == "__main__":
    from pipecat.runner.run import main
    main()
