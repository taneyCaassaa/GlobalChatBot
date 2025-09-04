from fastapi import WebSocket, Query, APIRouter
import base64
from io import BytesIO
import torch
import torchaudio
import numpy as np
import asyncio
import json
from backend.voice_functions import detect_voice_activity, transcribe_audio
from backend.chat_handlers import stream_chat_response, handle_chat_request
from backend.config import logger
from server.lifespan import VAD_SILENCE_THRESHOLD, VAD_BUFFER_SIZE
from fastapi import WebSocketDisconnect
from fastapi import APIRouter

router = APIRouter()

@router.websocket("/voice/chat")
async def voice_chat_websocket(
    websocket: WebSocket,
    session_id: str = Query(default="voice_default"),
):
    await websocket.accept()
    logger.info(f"🎤 Voice WebSocket connected for session: {session_id[:8]}")
    
    # Get Redis and MongoDB connections directly from router state
    redis_client = websocket.router.state.redis
    mongo_db = websocket.router.state.mongo
    
    try:
        while True:
            message = await websocket.receive_json()
            message_type = message.get("type")
            
            if message_type == "audio_chunk":
                # Handle streaming audio from client
                await handle_audio_chunk(websocket, message, session_id, redis_client, mongo_db)
                
            elif message_type == "end_recording":
                # Process accumulated audio and generate response
                await handle_end_recording(websocket, session_id, redis_client, mongo_db)
                
            elif message_type == "cancel":
                # Stop all processing
                await websocket.send_json({"type": "status", "message": "🛑 Cancelled"})
                
    except WebSocketDisconnect:
        logger.info(f"🔌 Voice WebSocket disconnected for session: {session_id[:8]}")
    except Exception as e:
        logger.error(f"❌ Voice WebSocket error: {str(e)}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass  # Connection might already be closed

# WebSocket helper functionsasync 
async def handle_audio_chunk(websocket: WebSocket, message: dict, session_id: str, redis, mongo):
    """Store audio chunk and perform real-time VAD with Silero"""
    try:
        chunk_data = message.get("data")
        chunk_index = message.get("index", 0)
        
        if chunk_data:
            chunk_key = f"voice:{session_id}:chunks"
            await redis.rpush(chunk_key, chunk_data)
            await redis.expire(chunk_key, 300)
            
            # Decode base64 to bytes (assume PCM for VAD)
            chunk_bytes = base64.b64decode(chunk_data)
            
            # Run VAD on chunk (short buffer for low latency)
            is_speech = await detect_voice_activity(chunk_bytes)
            await websocket.send_json({"type": "vad", "active": is_speech})
            
            # Track silence (similar to Whisper proposal)
            silence_key = f"voice:{session_id}:silence_count"
            if not is_speech:
                silence_count = int(await redis.get(silence_key) or 0) + 1
                await redis.set(silence_key, silence_count)
                if silence_count >= VAD_SILENCE_THRESHOLD:  # e.g., 3 consecutive silent chunks
                    # Auto-trigger end of recording
                    await handle_end_recording(websocket, session_id, redis, mongo)
                    await redis.delete(silence_key)  # Reset
            else:
                await redis.set(silence_key, 0)  # Reset on speech
        
        await websocket.send_json({"type": "chunk_received", "index": chunk_index})
        
    except Exception as e:
        logger.error(f"❌ Error handling audio chunk: {e}")
        await websocket.send_json({"type": "error", "message": str(e)})

async def handle_end_recording(websocket: WebSocket, session_id: str, redis, mongo):
    """Process accumulated audio chunks and generate response"""
    try:
        # Get all audio chunks (list of base64 strings)
        chunk_key = f"voice:{session_id}:chunks"
        audio_chunks = await redis.lrange(chunk_key, 0, -1)
        await redis.delete(chunk_key)  # Clean up
        
        if not audio_chunks:
            await websocket.send_json({"type": "status", "message": "No audio received"})
            return
        
        # Decode each chunk to waveform using torchaudio (handles WebM/Opus)
        waveforms = []
        sample_rates = set()
        for chunk in audio_chunks:
            try:
                chunk_bytes = base64.b64decode(chunk)
                with BytesIO(chunk_bytes) as buf:
                    wf, sr = torchaudio.load(buf)
                    if wf.shape[0] > 1:  # Convert to mono if stereo
                        wf = wf.mean(dim=0, keepdim=True)
                    waveforms.routerend(wf)
                    sample_rates.add(sr)
            except Exception as decode_err:
                logger.error(f"❌ Failed to decode audio chunk: {decode_err}")
                await websocket.send_json({"type": "error", "message": "Invalid audio chunk format"})
                return
        
        if not waveforms:
            await websocket.send_json({"type": "status", "message": "No valid audio decoded"})
            return
        
        if len(sample_rates) > 1:
            logger.error("❌ Inconsistent sample rates in audio chunks")
            await websocket.send_json({"type": "error", "message": "Inconsistent audio formats"})
            return
        
        sr = list(sample_rates)[0]
        full_waveform = torch.cat(waveforms, dim=1)  # Concatenate along time dimension
        
        # Save as WAV bytes for transcription
        with BytesIO() as wav_buf:
            torchaudio.save(wav_buf, full_waveform, sr, format="wav")
            wav_buf.seek(0)
            audio_blob = wav_buf.read()
        
        # Convert to transcript
        await websocket.send_json({"type": "status", "message": "🗣️ Converting speech to text..."})
        
        transcript = await transcribe_audio(audio_blob)
        
        if not transcript.strip():
            await websocket.send_json({"type": "status", "message": "❌ Could not understand speech"})
            return
        
        # Send transcript to client
        await websocket.send_json({"type": "transcript", "text": transcript})
        
        # Generate AI response with voice
        
        
    except Exception as e:
        logger.error(f"❌ Error in end_recording: {e}")
        await websocket.send_json({"type": "error", "message": str(e)})




