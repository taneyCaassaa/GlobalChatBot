import json
from typing import Any, Dict, List
import logging
import asyncio

from backend.api_functions import get_bio, search_images, get_news, web_search, get_datetime
from backend.config import logger, client

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_bio",
            "description": "Get biographical information about a person, celebrity, historical figure, or public personality. Use this when users ask 'who is [person]', want background information, or ask about someone's life story.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {
                        "type": "string",
                        "description": "The name of the person to get biography for (e.g., 'Virat Kohli', 'Elon Musk', 'Albert Einstein')",
                    }
                },
                "required": ["subject"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_images",
            "description": "Search for and display images related to any topic, person, place, object, animal, or concept. Use this when users want to see, show, find, display images/pictures, or ask for visual content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {
                        "type": "string",
                        "description": "What to search images for (e.g., 'Virat Kohli', 'sunset', 'Tesla car', 'lion')",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Number of images to return (1-10)",
                        "default": 2,
                    },
                },
                "required": ["subject"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": "Get exactly 3 recent news articles about the topic. Always returns maximum 2 articles to prevent response truncation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The news topic to search for (e.g., 'Virat Kohli', 'artificial intelligence', 'India', 'stock market')",
                    },
                    "max_items": {
                        "type": "integer",
                        "description": "Number of news articles to return (1-10)",
                        "default": 2,
                    },
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Perform a general web search to find current information, facts, prices, status, market data, weather, or any up-to-date information. Use this for factual questions, current prices (stocks, crypto), live data, weather, or when you need the most recent information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query (e.g., 'Nifty 50 current price', 'weather Mumbai today', 'Bitcoin price now')",
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "Number of search results to return (1-10)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_datetime",
            "description": "Get the current date and time in Indian Standard Time (IST). Use this when users ask for current date, time, today's date, what day it is, or any time-related queries.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

def _valid_items(items: Any) -> List[dict]:
    """Filter out invalid items and errors"""
    if not isinstance(items, list):
        return []
    return [x for x in items if isinstance(x, dict) and "error" not in x]

def format_function_result(fn_name: str, result: Any) -> str:
    """Minimal formatter – only returns errors, AI handles everything else."""

    # Handle dict errors
    if isinstance(result, dict) and "error" in result:
        return f"❌ **Error:** {result['error']}\n\n"

    # Handle empty or invalid results
    if not result or (isinstance(result, list) and len(result) == 0):
        return f"❌ **No results from {fn_name}.**\n\n"

    # Everything else: leave blank so AI formats
    return ""

async def handle_function_call(name: str, args: Dict[str, Any]) -> Any:
    """Handle function calls with detailed logging"""
    logger.info(f"🚀 Executing function: {name} with args: {args}")
    start_time = asyncio.get_event_loop().time()
    try:
        if name == "get_bio":
            result = await get_bio(args["subject"])
        elif name == "search_images":
            result = await search_images(args["subject"], args.get("max_results", 2))
        elif name == "get_news":
            result = await get_news(args["topic"], args.get("max_items", 3))
        elif name == "web_search":
            result = await web_search(args["query"], args.get("num_results", 5))
        elif name == "get_datetime":
            result = await get_datetime()
        else:
            result = f"❌ Unknown function: {name}"
            logger.error(result)
        elapsed = asyncio.get_event_loop().time() - start_time
        logger.info(f"✅ Function {name} completed in {elapsed:.2f}s")
        return result
    except Exception as e:
        elapsed = asyncio.get_event_loop().time() - start_time
        error_msg = f"❌ Error executing function {name} after {elapsed:.2f}s: {str(e)}"
        logger.error(error_msg)
        return {"error": error_msg}


async def _process_tool_calls(tool_calls, query: str):
    """Process multiple tool calls and return results"""
    all_tool_results = []
    formatted_results_to_show = []
    
    for tool_call in tool_calls:
        fn_name = tool_call.function.name
        fn_args = json.loads(tool_call.function.arguments or "{}")
        logger.info(f"🛠️ Calling tool: {fn_name} with args: {fn_args}")
        
        function_result = await handle_function_call(fn_name, fn_args)
        formatted_result = format_function_result(fn_name, function_result)
        
        if formatted_result.strip():
            formatted_results_to_show.append(formatted_result)
        
        all_tool_results.append({
            "tool_call_id": tool_call.id,
            "function_name": fn_name,
            "result": function_result,
            "formatted": formatted_result
        })
    
    return all_tool_results, formatted_results_to_show