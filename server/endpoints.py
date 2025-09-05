from fastapi import Depends, Request, HTTPException, Query
from fastapi.responses import StreamingResponse, JSONResponse, Response, FileResponse
import asyncio
import json
from server.rate_limiter import limiter
from server.dependencies import get_redis, get_mongo
from backend.voice_functions import transcribe_audio, detect_voice_activity
from backend.chat_handlers import stream_chat_response, handle_chat_request
import os

from backend.config import logger
from fastapi import APIRouter


router = APIRouter()


@router.get("/health")
async def health_check(
    redis_client=Depends(get_redis),
    mongo_db=Depends(get_mongo),
):
    try:
        # Test Redis
        await redis_client.ping()
        redis_status = "connected"
        
        # Test MongoDB
        await mongo_db.command("ping")
        mongo_status = "connected"
        
        return {
            "status": "healthy",
            "timestamp": asyncio.get_event_loop().time(),
            "services": {
                "redis": redis_status,
                "mongodb": mongo_status,
            },
            "version": "2.0"
        }
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        raise HTTPException(status_code=503, detail=f"Service unhealthy: {str(e)}")

# POST route for chatbot (non-streaming)
@router.post("/chatbot")
@limiter.limit("15/minute")
async def chatbot(
    request: Request,
    redis_client=Depends(get_redis),
    mongo_db=Depends(get_mongo),
):
    try:
        data = await request.json()
        user_query = data.get("query", "").strip()
        session_id = data.get("session_id", "default").strip()
        
        if not user_query:
            raise HTTPException(status_code=400, detail="Query is required and cannot be empty")
        
        if len(user_query) > 1000:
            raise HTTPException(status_code=400, detail="Query too long (max 1000 characters)")

        logger.info(f"🔍 POST request - Session: {session_id[:8]}, Query: {user_query[:50]}...")

        # Use the handle_chat_request function from main.py
        response = await handle_chat_request(
            query=user_query,
            session_id=session_id,
            redis=redis_client,
            mongo=mongo_db,
        )

        return JSONResponse(
            content={
                "response": response,
                "session_id": session_id,
                "timestamp": asyncio.get_event_loop().time(),
                "method": "post"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error in /chatbot: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

# GET route for streaming chatbot responses (SSE) - FIXED VERSION
@router.get("/chatbot/stream")
@limiter.limit("15/minute")
async def chatbot_stream(
    request: Request,
    query: str = Query(..., description="User query", min_length=1, max_length=1000),
    session_id: str = Query(default="default", description="Session ID", max_length=50),
    redis_client=Depends(get_redis),
    mongo_db=Depends(get_mongo),
):
    try:
        user_query = query.strip()
        session_id = session_id.strip() or "default"
        
        if not user_query:
            raise HTTPException(status_code=400, detail="Query cannot be empty")

        logger.info(f"🌊 SSE request - Session: {session_id[:8]}, Query: {user_query[:50]}...")

        async def sse_generator():
            try:
                logger.info(f"🌊 Starting SSE stream for query: {user_query[:50]}...")
                chunk_count = 0
                total_chars = 0
                
                # Use the stream_chat_response function from main.py
                async for chunk in stream_chat_response(
                    query=user_query,
                    session_id=session_id,
                    redis=redis_client,
                    mongo=mongo_db,
                ):
                    # Check if client disconnected
                    if await request.is_disconnected():
                        logger.info("🔌 Client disconnected, stopping stream")
                        break
                        
                    if chunk and chunk.strip():
                        chunk_count += 1
                        total_chars += len(chunk)
                        
                        try:
                            # Properly escape the chunk for JSON
                            escaped_chunk = json.dumps(chunk, ensure_ascii=False)
                            # Format as SSE event
                            formatted_chunk = f"data: {escaped_chunk}\n\n"
                            logger.debug(f"📤 SSE Chunk {chunk_count}: {len(chunk)} chars")
                            yield formatted_chunk
                            
                            # Ensure data is flushed immediately
                            await asyncio.sleep(0.001)  # Reduced delay for better streaming
                            
                        except (json.JSONEncodeError, UnicodeEncodeError) as e:
                            logger.error(f"❌ Encoding error for chunk: {e}")
                            # Send error chunk instead of breaking
                            error_chunk = f"data: {json.dumps('[Encoding Error]')}\n\n"
                            yield error_chunk
                            continue
                
                logger.info(f"✅ SSE stream completed. Chunks: {chunk_count}, Total chars: {total_chars}")
                yield "event: end\ndata: \"[DONE]\"\n\n"
                
            except asyncio.CancelledError:
                logger.info("🔄 SSE stream cancelled by client")
                yield "event: end\ndata: \"[CANCELLED]\"\n\n"
            except Exception as e:
                logger.error(f"💥 SSE Streaming error: {str(e)}", exc_info=True)
                error_msg = f"⛔ Streaming error: {str(e)}"
                yield f"event: error\ndata: {json.dumps(error_msg, ensure_ascii=False)}\n\n"
                yield "event: end\ndata: \"[ERROR]\"\n\n"

        return StreamingResponse(
            sse_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
                "Transfer-Encoding": "chunked",  # Ensure chunked encoding
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"💥 Error in /chatbot/stream: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal streaming error")

# Alternative streaming endpoint with better error handling
@router.get("/chatbot/stream-v2")
@limiter.limit("15/minute")
async def chatbot_stream_v2(
    request: Request,
    query: str = Query(..., description="User query", min_length=1, max_length=1000),
    session_id: str = Query(default="default", description="Session ID", max_length=50),
    redis_client=Depends(get_redis),
    mongo_db=Depends(get_mongo),
):
    """Alternative streaming endpoint with enhanced error handling and connection monitoring"""
    try:
        user_query = query.strip()
        session_id = session_id.strip() or "default"
        
        if not user_query:
            raise HTTPException(status_code=400, detail="Query cannot be empty")

        logger.info(f"🌊 SSE-v2 request - Session: {session_id[:8]}, Query: {user_query[:50]}...")

        async def enhanced_sse_generator():
            buffer = ""
            chunk_count = 0
            last_activity = asyncio.get_event_loop().time()
            
            try:
                # Send initial connection acknowledgment
                yield f"event: start\ndata: {json.dumps('')}\n\n"
                
                async for chunk in stream_chat_response(
                    query=user_query,
                    session_id=session_id,
                    redis=redis_client,
                    mongo=mongo_db,
                ):
                    current_time = asyncio.get_event_loop().time()
                    
                    # Check for client disconnect
                    if await request.is_disconnected():
                        logger.info("🔌 Client disconnected during streaming")
                        break
                    
                    # Timeout check (prevent hanging)
                    if current_time - last_activity > 30:  # 30 second timeout
                        logger.warning("⏰ Stream timeout - no activity")
                        yield f"event: timeout\ndata: {json.dumps('Stream timeout')}\n\n"
                        break
                    
                    if chunk:
                        chunk_count += 1
                        last_activity = current_time
                        
                        # Accumulate chunks to reduce overhead
                        buffer += chunk
                        
                        # Send when buffer reaches certain size or on newlines
                        if len(buffer) >= 100 or '\n' in chunk:
                            try:
                                safe_data = json.dumps(buffer, ensure_ascii=False)
                                sse_data = f"data: {safe_data}\n\n"
                                yield sse_data
                                
                                logger.debug(f"📤 Buffer sent - Chunk {chunk_count}, Size: {len(buffer)}")
                                buffer = ""
                                
                                # Small delay to prevent overwhelming
                                await asyncio.sleep(0.01)
                                
                            except Exception as encoding_error:
                                logger.error(f"❌ Buffer encoding error: {encoding_error}")
                                # Clear problematic buffer
                                buffer = ""
                                continue
                
                # Send any remaining buffer
                if buffer:
                    try:
                        safe_data = json.dumps(buffer, ensure_ascii=False)
                        yield f"data: {safe_data}\n\n"
                        logger.info(f"📤 Final buffer sent: {len(buffer)} chars")
                    except Exception as e:
                        logger.error(f"❌ Final buffer error: {e}")
                
                # Send completion event
                yield f"event: complete\ndata: {json.dumps(f'')}\n\n"
                logger.info(f"✅ SSE-v2 stream completed successfully - {chunk_count} chunks")
                
            except asyncio.CancelledError:
                logger.info("🔄 SSE-v2 stream cancelled")
                yield f"event: cancelled\ndata: {json.dumps('Stream was cancelled')}\n\n"
            except Exception as stream_error:
                logger.error(f"💥 SSE-v2 streaming error: {stream_error}", exc_info=True)
                error_data = json.dumps(f"Stream error: {str(stream_error)}")
                yield f"event: error\ndata: {error_data}\n\n"

        return StreamingResponse(
            enhanced_sse_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Keep-Alive": "timeout=30",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
                "Transfer-Encoding": "chunked",
            },
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"💥 Error in /chatbot/stream-v2: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal streaming error")

# Transcription endpoint
@router.post("/transcribe")
@limiter.limit("15/minute")
async def transcribe_audio_endpoint(request: Request):
    try:
        form = await request.form()
        if "audio" not in form:
            raise HTTPException(status_code=400, detail="Audio file required")
        audio_file = form["audio"]
        audio_bytes = await audio_file.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Empty audio file")
        text = await transcribe_audio(audio_bytes)
        return {"text": text}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Transcribe error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    

# Get conversation history
@router.get("/conversations/{session_id}")
@limiter.limit("30/minute")
async def get_conversation_history(
    session_id: str,
    limit: int = Query(default=50, le=100, ge=1),
    request: Request = None,
    redis_client=Depends(get_redis),
):
    try:
        messages = await redis_client.lrange(f"session:{session_id}:messages", -limit, -1)
        parsed_messages = []
        for msg in messages:
            try:
                parsed_msg = json.loads(msg)
                parsed_messages.routerend(parsed_msg)
            except json.JSONDecodeError:
                continue
        
        return {
            "session_id": session_id,
            "messages": parsed_messages,
            "count": len(parsed_messages)
        }
    except Exception as e:
        logger.error(f"❌ Error getting conversation history: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving conversation history")

# Clear conversation history
@router.delete("/conversations/{session_id}")
@limiter.limit("10/minute")
async def clear_conversation_history(
    session_id: str,
    request: Request = None,
    redis_client=Depends(get_redis),
):
    try:
        deleted = await redis_client.delete(f"session:{session_id}:messages")
        return {
            "session_id": session_id,
            "cleared": bool(deleted),
            "message": "Conversation history cleared" if deleted else "No conversation found"
        }
    except Exception as e:
        logger.error(f"❌ Error clearing conversation: {e}")
        raise HTTPException(status_code=500, detail="Error clearing conversation")

@router.get("/")
async def serve_chat():
    # Assuming chat.html is in project root
    return FileResponse(os.path.join(os.path.dirname(__file__), "..", "chat.html"))

# Keep your old JSON response at another endpoint
@router.get("/info")
async def root_info():
    return {
        "message": "🤖 AI Chatbot API v2.0",
        "description": "Enhanced chatbot with multi-function calling capabilities",
        "features": [
            "Real-time web search",
            "Image search and display",
            "Latest news retrieval",
            "Biography information",
            "Current date/time",
            "Multi-function complex queries",
            "Streaming responses (SSE)",
            "Voice chat via WebSocket",
            "Conversation history"
        ],
        "endpoints": {
            "POST /chatbot": "Send message (non-streaming)",
            "GET /chatbot/stream": "Send message (streaming SSE)",
            "GET /chatbot/stream-v2": "Enhanced streaming with better error handling",
            "WebSocket /voice/chat": "Voice chat with real-time audio",
            "GET /conversations/{session_id}": "Get conversation history",
            "DELETE /conversations/{session_id}": "Clear conversation history",
            "POST /transcribe": "Transcribe audio to text using Whisper",
            "GET /health": "Health check"
        },
        "version": "2.0",
        "status": "ready"
    }
