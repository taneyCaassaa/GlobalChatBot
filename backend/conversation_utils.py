import json
from typing import List, Dict, Any
import logging
from datetime import datetime
import asyncio 
from backend.config import logger, client

async def get_conversation_history(session_id: str, redis, limit: int = 10) -> List[Dict[str, Any]]:
    """Retrieve recent conversation history for context"""
    try:
        messages = await redis.lrange(f"session:{session_id}:messages", -limit, -1)
        parsed_messages = []
        for msg in messages:
            try:
                parsed_msg = json.loads(msg)
                # Only include role and content for OpenAI API
                if parsed_msg.get("role") in ["user", "assistant"]:
                    parsed_messages.append({
                        "role": parsed_msg["role"],
                        "content": parsed_msg["content"]
                    })
            except json.JSONDecodeError:
                continue
        
        logger.info(f"📚 Retrieved {len(parsed_messages)} conversation history messages for session {session_id[:8]}")
        return parsed_messages
    except Exception as e:
        logger.error(f"❌ Error retrieving conversation history: {e}")
        return []

def build_conversation_messages(query: str, history: List[Dict[str, Any]], system_prompt: str) -> List[Dict[str, Any]]:
    """Build the complete message list with system prompt, history, and current query"""
    messages = [{"role": "system", "content": system_prompt}]
    
    # Add conversation history (excluding the current query if it exists)
    for msg in history:
        if msg["content"] != query:  # Avoid duplicating the current query
            messages.append(msg)
    
    # Add current user query
    messages.append({"role": "user", "content": query})
    
    # Limit total messages to prevent context overflow (keep recent ~20 messages + system)
    if len(messages) > 21:  # system + 20 messages
        messages = [messages[0]] + messages[-(20):]  # Keep system prompt + last 20 messages
        logger.info(f"🔄 Trimmed conversation to last 20 messages to fit context window")
    
    return messages

async def _store_user_message(session_id: str, query: str, redis):
    """Store user message in Redis"""
    await redis.rpush(
        f"session:{session_id}:messages",
        json.dumps({"role": "user", "content": query, "timestamp": asyncio.get_event_loop().time()}),
    )

async def _store_assistant_message(session_id: str, response: str, redis):
    """Store assistant message in Redis"""
    await redis.rpush(
        f"session:{session_id}:messages",
        json.dumps({"role": "assistant", "content": response, "timestamp": asyncio.get_event_loop().time()}),
    )

async def _save_conversation(query: str, response: str, session_id: str, mongo):
    """Save conversation to MongoDB"""
    await mongo.conversations.insert_one({
        "user": query,
        "assistant": response,
        "session_id": session_id,
        "timestamp": datetime.now(),
    })