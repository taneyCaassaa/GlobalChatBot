from fastapi import FastAPI
from contextlib import asynccontextmanager
import os
from dotenv import load_dotenv
import logging
import redis.asyncio as redis
from motor.motor_asyncio import AsyncIOMotorClient
import torch
from io import BytesIO
import numpy as np
import torchaudio
from backend.config import logger


VAD_BUFFER_SIZE = 32000  # ~2s at 16kHz mono (adjust based on sample rate)
VAD_SILENCE_THRESHOLD = 1 # Number of silent buffers to consider speech end

# FastAPI lifespan for startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Redis connection
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    try:
        app.state.redis = redis.from_url(redis_url, decode_responses=True)
        await app.state.redis.ping()
        logger.info("✅ Connected to Redis")
    except Exception as e:
        logger.error(f"❌ Failed to connect to Redis: {e}")
        raise

    # MongoDB connection
    mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    try:
        mongo_client = AsyncIOMotorClient(mongo_uri)
        app.state.mongo = mongo_client.chatbot_db
        await app.state.mongo.command("ping")
        logger.info("✅ Connected to MongoDB")
    except Exception as e:
        logger.error(f"❌ Failed to connect to MongoDB: {e}")
        raise
        # Load Silero-VAD model
        
    try:
        global silero_model, silero_utils
        silero_model, silero_utils = torch.hub.load(repo_or_dir='snakers4/silero-vad', model='silero_vad')
        (get_speech_timestamps, save_audio, read_audio, VADIterator, collect_chunks) = silero_utils
        logger.info("✅ Loaded Silero-VAD model")
    except Exception as e:
        logger.error(f"❌ Failed to load Silero-VAD: {e}")
        raise
    
    yield

    # Cleanup
    try:
        await app.state.redis.close()
        mongo_client.close()
        # No specific cleanup for Silero, but can del if needed
        del silero_model
        del silero_utils
        logger.info("🔒 Closed all connections")
    except Exception as e:
        logger.error(f"❌ Error closing connections: {e}")
