import os
import json
import aiohttp
import logging
import asyncio
from typing import Any, Dict, AsyncGenerator, List, Optional
from openai import AsyncOpenAI
from dotenv import load_dotenv  # You can keep this if needed elsewhere, but it's now in config.py
from datetime import datetime
from zoneinfo import ZoneInfo
import base64
import tempfile
from pathlib import Path
import torch
import torchaudio
from typing import Tuple, Optional
import numpy as np
from io import BytesIO
from io import BytesIO

# NEW: Import shared globals from config.py
from backend.config import logger, client

# Modular imports (keep these as-is)
from backend.prompts import SYSTEM_PROMPT, SUMMARY_SYSTEM_PROMPT
from backend.api_functions import get_bio, search_images, get_news, web_search, get_datetime
from backend.voice_functions import transcribe_audio, detect_voice_activity
from backend.conversation_utils import get_conversation_history, build_conversation_messages, _store_user_message, _store_assistant_message, _save_conversation
from backend.tool_utils import tools, _valid_items, format_function_result, handle_function_call, _process_tool_calls
from backend.chat_handlers import handle_chat_request, stream_chat_response, stream_chat_with_voice

# Global model and utils (loaded later in app.py lifespan)
silero_model = None
silero_utils = None