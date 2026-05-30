"""Stocked — Mock pharmacy responder bots for testing.

Two personas: helpful pharmacist and grumpy pharmacist.
Both pull from medication_db.py so responses have real drug names,
prices, and stock status.

Used in MOCK MODE (automated) or with Cekura for evaluation.
Not used in DEMO MODE (you answer the phone yourself).
"""

import os
import random
import sys

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
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.services.gradium.tts import GradiumTTSService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.workers.runner import WorkerRunner

from nemotron_llm import VLLMOpenAILLMService
from nvidia_stt import NVidiaWebSocketSTTService
from medication_db import lookup_medication, MEDICATIONS

load_dotenv(override=True)

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")


def _build_helpful_prompt(pharmacy_name: str) -> str:
    """Build system prompt for a helpful pharmacist, including inventory context."""
    # Give the LLM a snapshot of what this pharmacy has
    from medication_db import PHARMACY_INVENTORY, _DEFAULT_STOCK
    stock = PHARMACY_INVENTORY.get(pharmacy_name, _DEFAULT_STOCK)
    stock_list = ", ".join(sorted(stock)[:8])  # Show first 8 to keep prompt short

    return (
        f"You are a friendly, helpful pharmacist answering the phone at {pharmacy_name}. "
        "You have access to your inventory and can check stock.\n\n"
        f"Medications currently IN STOCK at your pharmacy include: {stock_list}.\n"
        "For anything not on that list, tell the caller you're out of stock.\n\n"
        "Guidelines:\n"
        f"- Answer the phone warmly: 'Hello, {pharmacy_name}, this is the pharmacy. "
        "How can I help you?'\n"
        "- When asked about a medication, check if it's in your stock list above.\n"
        "- If in stock, give a price between eight and twenty-five dollars depending "
        "on the medication. Say something like 'Yes, we have that. For a thirty-day "
        "supply the cash price is about twelve ninety-nine.'\n"
        "- If NOT in stock, say 'I'm sorry, we're currently out of that one.'\n"
        "- Be cooperative with follow-up questions.\n"
        "- Keep responses brief and natural, like a real phone call.\n"
        "- When the caller thanks you or says goodbye, respond warmly and call end_call.\n"
        "- Responses are spoken aloud. No formatting.\n"
    )


def _build_grumpy_prompt(pharmacy_name: str) -> str:
    """Build system prompt for a grumpy pharmacist."""
    return (
        f"You are a grumpy, overworked pharmacist answering the phone at {pharmacy_name}. "
        "You're in the middle of filling prescriptions and annoyed at the interruption.\n\n"
        "Guidelines:\n"
        "- Answer curtly: 'Yeah, pharmacy.'\n"
        "- When asked about a medication, you ALWAYS say you're out of stock, "
        "regardless of what they ask for. Be dismissive: 'Nope. Don't have it. "
        "Been on backorder.'\n"
        "- Don't volunteer prices or alternatives.\n"
        "- If they press, snap: 'Look, I already told you we don't have it. "
        "Try Costco or something.'\n"
        "- Keep responses to one short sentence.\n"
        "- After 2-3 exchanges, say 'I gotta go' and call end_call.\n"
        "- Responses are spoken aloud. No formatting.\n"
    )


async def run_mock_pharmacy(transport, persona: str = "helpful",
                            pharmacy_name: str = "the pharmacy"):
    """Run a mock pharmacy bot with the given persona."""
    if persona == "helpful":
        prompt = _build_helpful_prompt(pharmacy_name)
    else:
        prompt = _build_grumpy_prompt(pharmacy_name)

    label = f"Mock {pharmacy_name} ({persona})"
    logger.info(f"Starting {label}")

    async def end_call(params: FunctionCallParams) -> None:
        """End the call."""
        logger.info(f"{label}: ending call")
        await params.llm.push_frame(EndTaskFrame(), FrameDirection.UPSTREAM)
        await params.result_callback(
            {"ok": True}, properties=FunctionCallResultProperties(run_llm=False)
        )

    tool_functions = [end_call]
    tools = ToolsSchema(standard_tools=tool_functions)

    stt = NVidiaWebSocketSTTService(
        url=os.getenv("NVIDIA_ASR_URL", "ws://44.241.251.184:8080"),
        strip_interim_prefix=True,
    )

    enable_thinking = os.getenv("NEMOTRON_ENABLE_THINKING", "false").lower() == "true"
    llm = VLLMOpenAILLMService(
        api_key=os.getenv("NEMOTRON_LLM_API_KEY", "EMPTY"),
        base_url=os.getenv("NEMOTRON_LLM_URL", "http://nemotron-fleet-alb-1322439314.us-west-2.elb.amazonaws.com/v1"),
        settings=VLLMOpenAILLMService.Settings(
            model=os.getenv("NEMOTRON_LLM_MODEL", "nvidia/nemotron-3-super"),
            system_instruction=prompt,
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
                params=VADParams(confidence=0.5, stop_secs=1.5),
            ),
            user_turn_strategies=UserTurnStrategies(
                start=[VADUserTurnStartStrategy()],
                stop=[SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=1.5)],
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
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info(f"{label}: client connected")
        context.add_message({
            "role": "user",
            "content": "Someone is calling your pharmacy. Answer the phone.",
        })
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"{label}: client disconnected")
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    await runner.run()


async def bot(runner_args: RunnerArguments):
    """Entry point — picks persona from stream params or randomly."""
    _, call_data = await parse_telephony_websocket(runner_args.websocket)
    body_data = call_data.get("body", {})
    persona = body_data.get("persona", random.choice(["helpful", "grumpy"]))
    pharmacy_name = body_data.get("pharmacy_name", "the pharmacy")

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
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=serializer,
        ),
    )

    await run_mock_pharmacy(transport, persona=persona, pharmacy_name=pharmacy_name)
