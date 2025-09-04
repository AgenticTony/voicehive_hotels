#!/usr/bin/env python3
"""
LiveKit Agent for VoiceHive Hotels
Handles SIP/PSTN calls with audio streaming to ASR/TTS services
"""

import asyncio
import os
from typing import Optional, Dict, Any
from dataclasses import dataclass

from dotenv import load_dotenv
from livekit import agents, rtc, api
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobRequest,
    WorkerOptions,
    cli,
)
import structlog

# Load environment variables
load_dotenv()

# Configure structured logging with PII redaction awareness
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


@dataclass
class CallContext:
    """Context for managing call state"""
    room: rtc.Room
    participant: Optional[rtc.RemoteParticipant] = None
    audio_track: Optional[rtc.RemoteAudioTrack] = None
    call_sid: Optional[str] = None
    hotel_id: Optional[str] = None
    language: str = "en"
    
    # External service connections
    orchestrator_url: str = os.getenv("ORCHESTRATOR_URL", "http://orchestrator:8080")
    asr_url: str = os.getenv("ASR_URL", "http://riva-proxy:8000")
    
    # Audio streaming
    audio_stream_task: Optional[asyncio.Task] = None
    is_streaming: bool = False


class VoiceHiveAgent:
    """Main agent class for handling voice calls"""
    
    def __init__(self, ctx: JobContext):
        self.ctx = ctx
        self.call_context: Optional[CallContext] = None
        self.room: Optional[rtc.Room] = None
        
    async def start(self):
        """Initialize and start the agent"""
        logger.info(f"Starting VoiceHive Agent for room: {self.ctx.room.name}")
        
        # Connect to the room
        await self.ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
        self.room = self.ctx.room
        
        # Initialize call context
        self.call_context = CallContext(room=self.room)
        
        # Extract metadata from job
        if self.ctx.job:
            metadata = self.ctx.job.metadata
            self.call_context.call_sid = metadata.get("call_sid")
            self.call_context.hotel_id = metadata.get("hotel_id")
            self.call_context.language = metadata.get("language", "en")
            
        # Set up event handlers
        self.room.on("participant_connected", self.on_participant_connected)
        self.room.on("track_subscribed", self.on_track_subscribed)
        self.room.on("track_unsubscribed", self.on_track_unsubscribed)
        self.room.on("participant_disconnected", self.on_participant_disconnected)
        self.room.on("data_received", self.on_data_received)
        
        # Notify orchestrator that agent is ready
        await self.notify_orchestrator("agent_ready", {
            "room_name": self.room.name,
            "call_sid": self.call_context.call_sid,
            "hotel_id": self.call_context.hotel_id
        })
        
        logger.info("VoiceHive Agent started successfully")
        
    async def on_participant_connected(self, participant: rtc.RemoteParticipant):
        """Handle participant joining the room"""
        logger.info(f"Participant connected: {participant.identity} (sid: {participant.sid})")
        
        # Store the participant reference
        self.call_context.participant = participant
        
        # Check if this is a SIP participant
        if participant.kind == rtc.ParticipantKind.SIP:
            logger.info("SIP participant detected, preparing for voice processing")
            
            # Notify orchestrator
            await self.notify_orchestrator("call_started", {
                "participant_sid": participant.sid,
                "participant_identity": participant.identity,
                "is_sip": True
            })
            
    async def on_track_subscribed(
        self,
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ):
        """Handle track subscription (audio/video)"""
        logger.info(
            f"Track subscribed: {publication.sid} "
            f"(kind: {track.kind}, source: {publication.source})"
        )
        
        # We only care about audio tracks
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            self.call_context.audio_track = track
            self.call_context.is_streaming = True
            
            # Start streaming audio to ASR
            self.call_context.audio_stream_task = asyncio.create_task(
                self.stream_audio_to_asr(track)
            )
            
    async def on_track_unsubscribed(
        self,
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ):
        """Handle track unsubscription"""
        logger.info(f"Track unsubscribed: {publication.sid}")
        
        if track == self.call_context.audio_track:
            self.call_context.is_streaming = False
            
            # Cancel audio streaming task
            if self.call_context.audio_stream_task:
                self.call_context.audio_stream_task.cancel()
                
    async def on_participant_disconnected(self, participant: rtc.RemoteParticipant):
        """Handle participant leaving the room"""
        logger.info(f"Participant disconnected: {participant.identity}")
        
        if participant == self.call_context.participant:
            # Notify orchestrator
            await self.notify_orchestrator("call_ended", {
                "participant_sid": participant.sid,
                "reason": "participant_disconnected"
            })
            
            # Clean up
            await self.cleanup()
            
    async def on_data_received(self, data: rtc.DataPacket):
        """Handle data messages from other participants"""
        if data.kind == rtc.DataPacketKind.RELIABLE:
            try:
                # Decode message
                message = data.data.decode('utf-8')
                logger.info(f"Received data message: {message}")
                
                # Handle different message types
                # This could be used for signaling, DTMF, etc.
                
            except Exception as e:
                logger.error(f"Error processing data packet: {e}")
                
    async def stream_audio_to_asr(self, track: rtc.RemoteAudioTrack):
        """Stream audio frames to ASR service"""
        logger.info("Starting audio streaming to ASR")
        
        try:
            # Create audio stream
            audio_stream = rtc.AudioStream(track)
            
            async for frame in audio_stream:
                if not self.call_context.is_streaming:
                    break
                    
                # Process audio frame
                # In a real implementation, this would:
                # 1. Convert frame to appropriate format
                # 2. Send to Riva ASR via gRPC
                # 3. Handle transcription results
                
                # For now, just log frame info
                logger.debug(
                    f"Audio frame: samples={frame.samples_per_channel}, "
                    f"sample_rate={frame.sample_rate}, channels={frame.num_channels}"
                )
                
                # TODO: Send to ASR service
                # await self.send_audio_to_asr(frame)
                
        except asyncio.CancelledError:
            logger.info("Audio streaming cancelled")
        except Exception as e:
            logger.error(f"Error in audio streaming: {e}")
    
    async def handle_transcription(self, text: str, is_final: bool, confidence: float = 1.0):
        """Handle transcription results from ASR"""
        logger.info(f"Transcription: '{text}' (final={is_final}, confidence={confidence})")

        # Send transcription to orchestrator
        await self.notify_orchestrator("transcription", {
            "text": text,
            "is_final": is_final,
            "confidence": confidence,
            "language": self.call_context.language
        })

        # Also send via dedicated transcription endpoint for immediate processing
        if is_final:
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    auth_header = {}
                    webhook_key = os.getenv("LIVEKIT_WEBHOOK_KEY", "")
                    if webhook_key:
                        auth_header["Authorization"] = f"Bearer {webhook_key}"
                    async with session.post(
                        f"{self.call_context.orchestrator_url}/v1/livekit/transcription",
                        json={
                            "call_sid": self.call_context.call_sid or self.room.name,
                            "text": text,
                            "language": self.call_context.language,
                            "confidence": confidence,
                            "is_final": is_final
                        },
                        headers={"Content-Type": "application/json", **auth_header}
                    ) as response:
                        if response.status == 200:
                            result = await response.json()
                            if result.get("intent_detected"):
                                logger.info(f"Intent detected: {result['intent_detected']}")
            except Exception as e:
                logger.error(f"Error sending transcription: {e}")
            
    async def publish_audio(self, audio_data: bytes, sample_rate: int = 16000):
        """Publish audio (TTS output) back to the room"""
        try:
            # Create audio source
            source = rtc.AudioSource(sample_rate, num_channels=1)
            track = rtc.LocalAudioTrack.create_audio_track("tts_output", source)
            
            # Publish track
            options = rtc.TrackPublishOptions(
                source=rtc.TrackSource.SOURCE_MICROPHONE,
            )
            publication = await self.room.local_participant.publish_track(track, options)
            
            # Send audio data
            # TODO: Convert audio_data to appropriate format and send
            
            logger.info("Published TTS audio to room")
            
        except Exception as e:
            logger.error(f"Error publishing audio: {e}")
            
    async def notify_orchestrator(self, event_type: str, data: Dict[str, Any]):
        """Send notifications to the orchestrator service"""
        try:
            import aiohttp
            import time
            
            # Add call_sid to all events
            if self.call_context.call_sid:
                data["call_sid"] = self.call_context.call_sid
            
            payload = {
                "event_type": event_type,
                "call_sid": self.call_context.call_sid or self.room.name,
                "timestamp": time.time(),
                "data": data
            }
            
            # Get webhook key from environment or config
            webhook_key = os.getenv("LIVEKIT_WEBHOOK_KEY", "")
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.call_context.orchestrator_url}/call/event",
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {webhook_key}"
                    }
                ) as response:
                    if response.status != 200:
                        logger.error(
                            f"Failed to notify orchestrator: {response.status} - "
                            f"{await response.text()}"
                        )
                    else:
                        logger.debug(f"Notified orchestrator: {event_type}")
                        
        except Exception as e:
            logger.error(f"Error notifying orchestrator: {e}")
            
    async def cleanup(self):
        """Clean up resources"""
        logger.info("Cleaning up agent resources")
        
        # Cancel audio streaming
        if self.call_context and self.call_context.audio_stream_task:
            self.call_context.audio_stream_task.cancel()
            
        # Disconnect from room
        if self.room:
            await self.room.disconnect()
            

async def entrypoint(ctx: JobContext):
    """Agent entrypoint function"""
    logger.info(f"Agent entrypoint called for job: {ctx.job.id if ctx.job else 'unknown'}")
    
    # Create and start agent
    agent = VoiceHiveAgent(ctx)
    await agent.start()
    
    # Keep agent running until room is disconnected
    try:
        while ctx.room.connection_state == rtc.ConnectionState.CONN_CONNECTED:
            await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"Agent error: {e}")
    finally:
        await agent.cleanup()
        

async def request_fnc(req: JobRequest) -> agents.JobAcceptResponse:
    """Function to determine if agent should handle the job"""
    logger.info(f"Received job request for room: {req.room.name}")
    
    # Accept all jobs for now
    # In production, you might want to check:
    # - Agent capacity
    # - Room metadata
    # - SIP configuration
    
    return agents.JobAcceptResponse(accept=True)


if __name__ == "__main__":
    # Run the agent
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            request_fnc=request_fnc,
            worker_type=agents.WorkerType.ROOM,
            max_idle_time=60.0,  # Keep worker alive for 60s after job ends
            load_fnc=lambda: 0.0,  # Simple load calculation
            load_threshold=0.8,
        )
    )
