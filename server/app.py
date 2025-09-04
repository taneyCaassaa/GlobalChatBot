import asyncio
import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from dotenv import load_dotenv
from fastapi import APIRouter
from server.rate_limiter import limiter
# NEW: Import from new modular files
from server.lifespan import lifespan
from server.dependencies import get_redis, get_mongo
from server.endpoints import *  # Imports all endpoints (health, chatbot, streams, etc.)
from server.websocket_handlers import *  # Imports WebSocket and helpers
from server.rate_limiter import limiter
from server.endpoints import router as endpoints_router
from server.websocket_handlers import router as websocket_router 

load_dotenv()

# Setup logging (if not imported from config.py; adjust as needed)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Rate limiter


# Enable CORS
origins = [
    "http://localhost:3000",
    "http://localhost:8501",
    "http://127.0.0.1:8501",
    "*"  # Remove in production
]

app = FastAPI(
    lifespan=lifespan,
    title="AI Chatbot API",
    version="2.0",
    description="Enhanced chatbot with multi-function calling, image search, news, and web search capabilities"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(endpoints_router)
app.include_router(websocket_router) 
# No need to redefine dependencies, endpoints, or WebSocket here—they're imported
