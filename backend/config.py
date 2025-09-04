import os
from dotenv import load_dotenv
import logging
from openai import AsyncOpenAI

load_dotenv()

# Enhanced logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Env variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SERP_API_KEY = os.getenv("SERP_API_KEY") or os.getenv("SERPAPI_KEY")
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")

# Log API key status
logger.info("API Keys Status:")
logger.info(f"OPENAI_API_KEY: {'✅ SET' if OPENAI_API_KEY else '❌ MISSING'}")
logger.info(f"SERP_API_KEY: {'✅ SET' if SERP_API_KEY else '❌ MISSING'}")
logger.info(f"GNEWS_API_KEY: {'✅ SET' if GNEWS_API_KEY else '❌ MISSING'}")

# Raise error if OpenAI key missing
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable is required")

client = AsyncOpenAI(api_key=OPENAI_API_KEY)
