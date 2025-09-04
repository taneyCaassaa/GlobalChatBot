from openai import AsyncOpenAI
import logging
import asyncio
from typing import AsyncGenerator
from backend.prompts import SYSTEM_PROMPT, SUMMARY_SYSTEM_PROMPT
from backend.conversation_utils import get_conversation_history, build_conversation_messages, _store_user_message, _store_assistant_message, _save_conversation
from backend.tool_utils import tools, _process_tool_calls,handle_function_call, format_function_result
from backend.config import client, logger
import json

async def handle_chat_request(query: str, session_id: str, redis, mongo) -> str:
    """Enhanced non-streaming chat handler with conversation history context"""
    logger.info(f"💬 Processing chat request for session {session_id[:8]}...")
    logger.info(f"📝 User Query: {query}")

    try:
        # Get conversation history before adding the new user message
        conversation_history = await get_conversation_history(session_id, redis, limit=10)
        
        # Store the current user message
        await _store_user_message(session_id, query, redis)

        # Build messages with conversation history
        messages = build_conversation_messages(query, conversation_history, SYSTEM_PROMPT)
        
        logger.info(f"📚 Using {len(messages)} messages for context (including system prompt)")

        # First OpenAI call to determine if functions are needed
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.3,
        )

        message = response.choices[0].message

        # Handle tool calls
        if message.tool_calls:
            logger.info(f"🎯 OpenAI requested {len(message.tool_calls)} tool calls")
            
            all_tool_results, formatted_results_to_show = await _process_tool_calls(message.tool_calls, query)
            
            # Prepare messages for the second OpenAI call with tool results
            summary_messages = [
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT}
            ]
            
            # Add recent conversation history for context
            for msg in conversation_history[-5:]:  # Only last 5 messages for summary context
                if msg["content"] != query:  # Avoid duplicating current query
                    summary_messages.append(msg)
            
            # Add current interaction
            summary_messages.extend([
                {"role": "user", "content": query},
                {"role": "assistant", "content": message.content, "tool_calls": message.tool_calls}
            ])
            
            # Add tool results
            for tool_result in all_tool_results:
                summary_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_result["tool_call_id"],
                    "content": str(tool_result["result"])
                })
            
            # Second OpenAI call to generate final response
            followup_response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=summary_messages,
                temperature=0.3,
                max_tokens=1000,  # Increased to ensure complete responses
            )
            
            ai_response = followup_response.choices[0].message.content or ""
            
            if formatted_results_to_show:
                combined_results = "\n".join(formatted_results_to_show)
                final_response = f"{combined_results}\n\n\n{ai_response}"
            else:
                final_response = f"\n\n{ai_response}"
            
        else:
            # No tools needed, use the direct response
            final_response = message.content or "I couldn't process your request."
            logger.info("🤖 Regular response (no function calls)")

        # Store conversation
        await _save_conversation(query, final_response, session_id, mongo)
        await _store_assistant_message(session_id, final_response, redis)
        
        logger.info("✅ Chat request completed successfully")
        return final_response
        
    except Exception as e:
        error_msg = f"❌ Error in chat request: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return error_msg

async def stream_chat_response(query: str, session_id: str, redis, mongo) -> AsyncGenerator[str, None]:
    """Enhanced streaming response with conversation history context"""
    logger.info(f"🌊 Starting stream for session {session_id[:8]}...")
    logger.info(f"📝 Query: {query}")

    try:
        # Get conversation history before adding the new user message
        conversation_history = await get_conversation_history(session_id, redis, limit=10)
        
        # Store the current user message
        await _store_user_message(session_id, query, redis)

        # Build messages with conversation history
        messages = build_conversation_messages(query, conversation_history, SYSTEM_PROMPT)
        
        logger.info(f"📚 Using {len(messages)} messages for context (including system prompt)")

        # First OpenAI call to determine if functions are needed
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.3,
        )

        message = response.choices[0].message
        full_response = ""

        # Handle tool calls
        if message.tool_calls:
            logger.info(f"🎯 OpenAI requested {len(message.tool_calls)} tool calls")
            
            all_tool_results = []
            formatted_results_to_show = []
            
            for i, tool_call in enumerate(message.tool_calls, 1):
                fn_name = tool_call.function.name
                fn_args = json.loads(tool_call.function.arguments or "{}")
                
                # Show progress for all functions
                progress_msg = f"\n\n"
                yield progress_msg
                full_response += progress_msg
                
                function_result = await handle_function_call(fn_name, fn_args)
                formatted_result = format_function_result(fn_name, function_result)
                
                # Stream formatted results immediately
                if formatted_result.strip():
                    yield formatted_result
                    full_response += formatted_result
                    formatted_results_to_show.append(formatted_result)
                
                all_tool_results.append({
                    "tool_call_id": tool_call.id,
                    "function_name": fn_name,
                    "result": function_result,
                    "formatted": formatted_result
                })
                
                # Small delay between functions
                if i < len(message.tool_calls):
                    await asyncio.sleep(0.3)
            
            # Generate AI summary
            summary_header = "\n\n\n"
            yield summary_header
            full_response += summary_header
            
            # Prepare messages for the summary call with conversation context
            summary_messages = [
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT}
            ]
            
            # Add recent conversation history for context
            for msg in conversation_history[-5:]:  # Only last 5 messages for summary context
                if msg["content"] != query:  # Avoid duplicating current query
                    summary_messages.append(msg)
            
            # Add current interaction
            summary_messages.extend([
                {"role": "user", "content": query},
                {"role": "assistant", "content": message.content, "tool_calls": message.tool_calls}
            ])
            
            # Add tool results
            for tool_result in all_tool_results:
                summary_messages.append({
                    "role": "tool", 
                    "tool_call_id": tool_result["tool_call_id"],
                    "content": str(tool_result["result"])
                })
            
            # Stream the AI summary with enhanced settings
            summary_stream = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=summary_messages,
                stream=True,
                temperature=0.3,
                max_tokens=1000,  # Increased for complete responses
            )
            
            summary_text = ""
            chunk_buffer = ""
            
            async for chunk in summary_stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if hasattr(delta, "content") and delta.content:
                        content = delta.content
                        summary_text += content
                        full_response += content
                        chunk_buffer += content
                        
                        # Stream in larger chunks for better performance
                        if len(chunk_buffer) >= 5 or content.endswith(('.', '!', '?', '\n')):
                            yield chunk_buffer
                            chunk_buffer = ""
                        
                        # Small delay for smooth streaming
                        await asyncio.sleep(0.01)
            
            # Send any remaining buffer
            if chunk_buffer:
                yield chunk_buffer
                
        else:
            # No tools needed, stream regular conversation with context
            logger.info("💬 Regular conversation with context - streaming response")
            
            enhanced_system = """You are a helpful and knowledgeable assistant with access to conversation history. 

Use the conversation history to provide contextual responses. Reference previous discussions when relevant and maintain continuity in the conversation.

If users ask for current information, real-time data, images, news, or biographies in the future, let them know you have access to tools that can help with that, but for this response, provide what you can from your general knowledge and conversation context.

Keep responses conversational and helpful."""

            # Use conversation messages for regular chat too
            chat_messages = build_conversation_messages(query, conversation_history, enhanced_system)

            stream = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=chat_messages,
                stream=True,
                temperature=0.7,
                max_tokens=1000,  # Ensure complete responses
            )

            chunk_buffer = ""
            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if hasattr(delta, "content") and delta.content:
                        content = delta.content
                        full_response += content
                        chunk_buffer += content
                        
                        # Stream in meaningful chunks
                        if len(chunk_buffer) >= 8 or content.endswith(('.', '!', '?', '\n')):
                            yield chunk_buffer
                            chunk_buffer = ""
                        
                        await asyncio.sleep(0.01)
            
            # Send any remaining buffer
            if chunk_buffer:
                yield chunk_buffer

        # Ensure we have a complete response before saving
        if full_response.strip():
            await _save_conversation(query, full_response, session_id, mongo)
            await _store_assistant_message(session_id, full_response, redis)
            logger.info(f"✅ Complete response saved: {len(full_response)} characters")
        else:
            logger.warning("⚠️ Empty response generated")
        
        logger.info("✅ Stream completed successfully")

    except Exception as e:
        error_msg = f"⛔ Streaming error: {str(e)}"
        logger.error(error_msg, exc_info=True)
        yield error_msg

async def stream_chat_with_voice(query: str, session_id: str, redis, mongo):
    """Enhanced streaming chat that yields both text and audio chunks"""
    logger.info(f"🎤 Starting voice stream for session {session_id[:8]}...")
    
    try:
        # Get conversation history
        conversation_history = await get_conversation_history(session_id, redis, limit=10)
        
        # Store user message
        await _store_user_message(session_id, query, redis)
        
        # Build messages with conversation history
        messages = build_conversation_messages(query, conversation_history, SYSTEM_PROMPT)
        
        # First OpenAI call to determine if functions are needed
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.3,
        )

        message = response.choices[0].message
        full_response = ""

        # Handle tool calls
        if message.tool_calls:
            logger.info(f"🎯 Processing {len(message.tool_calls)} tool calls for voice")
            
            all_tool_results, formatted_results_to_show = await _process_tool_calls(message.tool_calls, query)
            
            # Stream formatted results as text
            for formatted_result in formatted_results_to_show:
                if formatted_result.strip():
                    yield {"type": "text", "content": formatted_result}
                    full_response += formatted_result
            
            # Generate AI summary with streaming
            summary_header = "\n\n\n"
            yield {"type": "text", "content": summary_header}
            full_response += summary_header
            
            # Prepare messages for summary
            summary_messages = [
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT}
            ]
            
            for msg in conversation_history[-5:]:
                if msg["content"] != query:
                    summary_messages.append(msg)
            
            summary_messages.extend([
                {"role": "user", "content": query},
                {"role": "assistant", "content": message.content, "tool_calls": message.tool_calls}
            ])
            
            for tool_result in all_tool_results:
                summary_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_result["tool_call_id"],
                    "content": str(tool_result["result"])
                })
            
            # Stream AI summary with voice
            summary_stream = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=summary_messages,
                stream=True,
                temperature=0.3,
                max_tokens=1000,
            )
            
            text_buffer = ""
            
            async for chunk in summary_stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if hasattr(delta, "content") and delta.content:
                        content = delta.content
                        full_response += content
                        text_buffer += content
                        
                        # Send text immediately
                        yield {"type": "text", "content": content}
                        
                        
        else:
            # No tools needed, regular conversation with voice
            enhanced_system = """You are a helpful assistant with conversation history context. 
            Provide conversational responses and reference previous discussions when relevant."""
            
            chat_messages = build_conversation_messages(query, conversation_history, enhanced_system)
            
            stream = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=chat_messages,
                stream=True,
                temperature=0.7,
                max_tokens=1000,
            )
            
            text_buffer = ""
            
            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if hasattr(delta, "content") and delta.content:
                        content = delta.content
                        full_response += content
                        text_buffer += content
                        
                        # Send text immediately
                        yield {"type": "text", "content": content}
                        
                        # Convert to speech at natural break points

        # Save conversation
        if full_response.strip():
            await _save_conversation(query, full_response, session_id, mongo)
            await _store_assistant_message(session_id, full_response, redis)
        
        logger.info("✅ Voice stream completed successfully")
        
    except Exception as e:
        error_msg = f"❌ Voice streaming error: {str(e)}"
        logger.error(error_msg, exc_info=True)
        yield {"type": "text", "content": error_msg}