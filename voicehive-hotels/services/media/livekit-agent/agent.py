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
                # Convert frame to appropriate format and send to ASR
                try:
                    # Convert LiveKit audio frame to bytes
                    audio_data = await self._convert_frame_to_bytes(frame)
                    
                    # Send to ASR service
                    await self.send_audio_to_asr(audio_data, frame.sample_rate)
                    
                    logger.debug(
                        f"Audio frame processed: samples={frame.samples_per_channel}, "
                        f"sample_rate={frame.sample_rate}, channels={frame.num_channels}"
                    )
                    
                except Exception as e:
                    logger.error(f"Error processing audio frame: {e}")
                    # Continue processing other frames
                
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
            
            # Convert audio data to appropriate format and send
            await self._send_audio_to_track(source, audio_data, sample_rate)

            logger.info("Published TTS audio to room")
            
        except Exception as e:
            logger.error(f"Error publishing audio: {e}")

    async def _send_audio_to_track(self, source: rtc.AudioSource, audio_data: bytes, sample_rate: int):
        """Convert audio data to LiveKit frames and send to audio source"""
        try:
            import numpy as np

            # Convert bytes to numpy array (assuming 16-bit PCM)
            audio_array = np.frombuffer(audio_data, dtype=np.int16)

            # Calculate frame parameters
            # LiveKit typically uses 10ms frames (480 samples at 48kHz, 160 samples at 16kHz)
            frame_duration_ms = 10
            samples_per_frame = int(sample_rate * frame_duration_ms / 1000)

            # Ensure we have enough samples
            if len(audio_array) == 0:
                logger.warning("Empty audio data received")
                return

            # Handle sample rate conversion if needed
            target_sample_rate = source.sample_rate
            if sample_rate != target_sample_rate:
                audio_array = await self._resample_audio(audio_array, sample_rate, target_sample_rate)
                sample_rate = target_sample_rate
                samples_per_frame = int(target_sample_rate * frame_duration_ms / 1000)

            # Split audio into frames and send
            num_frames = (len(audio_array) + samples_per_frame - 1) // samples_per_frame

            for i in range(num_frames):
                start_idx = i * samples_per_frame
                end_idx = min((i + 1) * samples_per_frame, len(audio_array))

                # Extract frame data
                frame_data = audio_array[start_idx:end_idx]

                # Pad frame if necessary (last frame might be shorter)
                if len(frame_data) < samples_per_frame:
                    frame_data = np.pad(frame_data, (0, samples_per_frame - len(frame_data)), 'constant')

                # Create AudioFrame
                # LiveKit expects planar format for multi-channel, but we're using mono
                frame = rtc.AudioFrame(
                    data=frame_data.tobytes(),
                    sample_rate=sample_rate,
                    num_channels=1,
                    samples_per_channel=len(frame_data)
                )

                # Push frame to source
                await source.capture_frame(frame)

                # Small delay to simulate real-time playback
                frame_duration_seconds = len(frame_data) / sample_rate
                await asyncio.sleep(frame_duration_seconds)

            logger.debug(f"Sent {num_frames} audio frames to track")

        except Exception as e:
            logger.error(f"Error sending audio to track: {e}")

    async def _resample_audio(self, audio_array: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
        """Simple audio resampling using linear interpolation"""
        try:
            import numpy as np

            if source_rate == target_rate:
                return audio_array

            # Calculate resampling ratio
            ratio = target_rate / source_rate

            # Calculate new length
            new_length = int(len(audio_array) * ratio)

            # Create new sample indices
            old_indices = np.linspace(0, len(audio_array) - 1, new_length)

            # Interpolate
            resampled = np.interp(old_indices, np.arange(len(audio_array)), audio_array.astype(float))

            return resampled.astype(np.int16)

        except Exception as e:
            logger.error(f"Error resampling audio: {e}")
            return audio_array  # Return original on error

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
            
    async def _convert_frame_to_bytes(self, frame: rtc.AudioFrame) -> bytes:
        """Convert LiveKit audio frame to raw bytes for ASR"""
        try:
            # LiveKit AudioFrame provides direct access to audio data
            # The frame.data is already in the correct format (16-bit PCM)
            import numpy as np
            
            # Get audio data as numpy array
            # LiveKit frames are in planar format, convert to interleaved if needed
            if frame.num_channels == 1:
                # Mono audio - direct conversion
                audio_data = frame.data
            else:
                # Multi-channel audio - convert to mono by averaging channels
                samples_per_channel = frame.samples_per_channel
                audio_array = np.frombuffer(frame.data, dtype=np.int16)
                
                # Reshape to [channels, samples] and average across channels
                audio_array = audio_array.reshape(frame.num_channels, samples_per_channel)
                mono_audio = np.mean(audio_array, axis=0).astype(np.int16)
                audio_data = mono_audio.tobytes()
            
            return audio_data
            
        except Exception as e:
            logger.error(f"Error converting audio frame: {e}")
            # Return empty bytes on error
            return b''
    
    async def send_audio_to_asr(self, audio_data: bytes, sample_rate: int):
        """Send audio data to ASR service for transcription"""
        try:
            import base64
            import aiohttp
            
            # Encode audio data as base64
            audio_b64 = base64.b64encode(audio_data).decode()
            
            # Prepare request payload
            payload = {
                "audio_data": audio_b64,
                "language": self.call_context.language,
                "sample_rate": sample_rate,
                "encoding": "LINEAR16"
            }
            
            # Send to ASR service
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.call_context.asr_url}/transcribe",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=5.0)
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        
                        # Extract transcription results
                        transcript = result.get("transcript", "")
                        confidence = result.get("confidence", 0.0)
                        
                        # Only process if we have meaningful transcription
                        if transcript.strip() and confidence > 0.3:
                            await self.handle_transcription(
                                text=transcript,
                                is_final=True,  # Offline transcription is always final
                                confidence=confidence
                            )
                    else:
                        logger.warning(f"ASR service returned status {response.status}")
                        
        except asyncio.TimeoutError:
            logger.warning("ASR service timeout")
        except Exception as e:
            logger.error(f"Error sending audio to ASR: {e}")
    
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
