import tempfile
from pathlib import Path
import torch
import torchaudio
import numpy as np
from io import BytesIO
from openai import AsyncOpenAI 
import logging
import asyncio 
from backend.config import logger, client

async def transcribe_audio(audio_data: bytes) -> str:
    """Convert audio bytes to text using OpenAI Whisper."""
    try:
        if not audio_data:
            return ""
        
        # Create temporary file
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as temp_file:
            temp_file.write(audio_data)
            temp_path = temp_file.name
        
        # Use OpenAI Whisper API
        with open(temp_path, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text"
            )
        
        # Cleanup
        Path(temp_path).unlink()
        
        logger.info(f"🗣️ Transcript: {transcript[:100]}...")
        return transcript.strip()
    
    except Exception as e:
        logger.error(f"❌ Error in speech-to-text: {str(e)}")
        return ""

# Add this function for VAD detection on audio buffers
async def detect_voice_activity(audio_data: bytes, threshold: float = 0.5) -> bool:
    """Use Silero-VAD to detect voice activity in an audio buffer.
    Supports WebM/Opus formats via torchaudio decoding.
    Returns True if speech probability > threshold.
    """
    global silero_model, silero_utils
    if silero_model is None or silero_utils is None:
        raise ValueError("Silero-VAD model not loaded")

    try:
        # Decode audio bytes (handles WebM/Opus)
        with BytesIO(audio_data) as buf:
            waveform, sample_rate = torchaudio.load(buf)

        # Ensure mono
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)

        # Resample to 16000 Hz if needed
        if sample_rate != 16000:
            resampler = torchaudio.transforms.Resample(sample_rate, 16000)
            waveform = resampler(waveform)

        # Get speech probability
        speech_prob = silero_model(waveform, 16000).item()

        is_speech = speech_prob > threshold
        logger.info(f"🛡️ VAD Result: {'Speech detected' if is_speech else 'No speech'} (prob: {speech_prob:.2f})")
        return is_speech

    except Exception as e:
        logger.error(f"❌ Silero-VAD Error: {str(e)}")
        return False  # Fail-safe: No speech on error

