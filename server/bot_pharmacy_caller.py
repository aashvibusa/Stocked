"""Stocked — Arya outbound pharmacy-calling bot.

Each instance calls one pharmacy and asks if they have the requested
medication in stock, at what price. Results go to call_log for
aggregation and SMS.

Pipeline: NVIDIA Nemotron Speech Streaming STT -> Nemotron-3-Super-120B LLM -> Gradium TTS
"""

import os

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
import call_log

load_dotenv(override=True)


async def run_bot(transport, medication: str, dosage: str,
                  pharmacy_name: str, pharmacy_address: str,
                  request_id: str, caller_name: str = "a patient"):
    """Run the outbound pharmacy caller bot."""
    logger.info(f"Arya calling {pharmacy_name} for {caller_name}: {medication} {dosage}")

    call_result: dict = {"in_stock": None, "price": None}
    transcript_lines: list[str] = []

    async def record_result(
        params: FunctionCallParams,
        in_stock: bool,
        price: str | None = None,
    ) -> None:
        """Record the pharmacy's response about medication availability.

        Args:
            in_stock: Whether the pharmacy has the medication in stock.
            price: Price quoted by the pharmacy, if available (e.g. "12.99").
        """
        call_result["in_stock"] = in_stock
        call_result["price"] = price
        logger.info(f"Result from {pharmacy_name}: in_stock={in_stock}, price={price}")

        await call_log.update_pharmacy_call(
            request_id=request_id,
            pharmacy_name=pharmacy_name,
            pharmacy_address=pharmacy_address,
            status="completed",
            in_stock=in_stock,
            price=price,
            transcript="\n".join(transcript_lines),
        )

        await params.result_callback({"ok": True, "recorded": True})

    async def end_call(params: FunctionCallParams) -> None:
        """End the call after saying goodbye."""
        if call_result["in_stock"] is None:
            await call_log.update_pharmacy_call(
                request_id=request_id,
                pharmacy_name=pharmacy_name,
                pharmacy_address=pharmacy_address,
                status="completed",
                in_stock=False,
                price=None,
                transcript="\n".join(transcript_lines),
            )
        logger.info(f"Ending call with {pharmacy_name}")
        await params.llm.push_frame(EndTaskFrame(), FrameDirection.UPSTREAM)
        await params.result_callback(
            {"ok": True}, properties=FunctionCallResultProperties(run_llm=False)
        )

    tool_functions = [record_result, end_call]
    tools = ToolsSchema(standard_tools=tool_functions)

    system_instruction = (
        f"You are Arya, a pharmacy assistant from Stocked. You are calling "
        f"{pharmacy_name} on behalf of {caller_name} to check if they have "
        f"a prescription medication in stock.\n\n"
        f"The prescription is: {medication} {dosage}\n\n"
        "How to introduce yourself:\n"
        f"- 'Hi, this is Arya calling from Stocked on behalf of {caller_name}. "
        f"I'm checking if you have {medication} {dosage} available for pickup?'\n\n"
        "Guidelines:\n"
        "- Be polite and professional, like a real person calling a pharmacy.\n"
        "- Listen for whether they have it in stock and the price.\n"
        "- If they give a price, note it. If they say it depends on insurance, "
        "ask for the cash price or say 'just the retail price is fine.'\n"
        "- Once you have a clear yes/no and ideally a price, call record_result.\n"
        "- Thank them, say goodbye, and call end_call.\n"
        "- Keep it brief. 1-2 sentences per turn. Don't over-explain.\n"
        "- If they're rude or unhelpful, stay polite, try once more, then record "
        "what you have and hang up.\n"
        "- Responses are spoken aloud. No formatting.\n"
    )

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
        logger.info(f"Arya connected to {pharmacy_name}")
        context.add_message({
            "role": "user",
            "content": "The pharmacy just picked up. Introduce yourself as Arya from Stocked and ask about the medication.",
        })
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"Arya disconnected from {pharmacy_name}")
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    await runner.run()


async def bot(runner_args: RunnerArguments):
    """Entry point called from the outbound server WebSocket handler."""
    _, call_data = await parse_telephony_websocket(runner_args.websocket)
    body_data = call_data.get("body", {})

    medication = body_data.get("medication", "unknown")
    dosage = body_data.get("dosage", "unknown")
    pharmacy_name = body_data.get("pharmacy_name", "Unknown Pharmacy")
    pharmacy_address = body_data.get("pharmacy_address", "")
    request_id = body_data.get("request_id", "unknown")
    caller_name = body_data.get("caller_name", "a patient")

    logger.info(f"Arya outbound for {pharmacy_name}: {medication} {dosage} (for {caller_name})")

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

    await run_bot(transport, medication, dosage, pharmacy_name, pharmacy_address,
                  request_id, caller_name)
