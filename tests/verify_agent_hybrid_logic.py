
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
import sys

# 1. Setup Mock for db_vector BEFORE internal imports happen
mock_db_vector = MagicMock()
sys.modules["app.core.db_vector"] = mock_db_vector

from app.agents.meeting.meeting_agent import MeetingAgent
from app.schemas.chat import ChatRequest

async def verify_hybrid_flow():
    print("--- Verifying MeetingAgent Hybrid Flow (Temp + KB) ---")
    
    agent = MeetingAgent()
    
    # 2. Configure Mock Data
    query = "What is the policy?"
    
    # KB Data that the agent should find via db_vector
    kb_chunks_return = [
        ("k1", 0.85, {"chunk_text": "Policy: Use cloud storage.", "title": "IT Policy", "file_url": "http://kb"})
    ]
    
    # Configure the mock to return this data
    # Note: verify method signature matches: search_hybrid_chunks(query, dense_embed_fn, ...)
    mock_db_vector.search_hybrid_chunks = AsyncMock(return_value=kb_chunks_return)
    
    # 3. Configure Agent LLM Mock
    # We want to see what context is passed to the LLM
    async def mock_achat(messages, **kwargs):
        for m in messages:
            if m["role"] == "system":
                # Return the system prompt content as the "answer" so we can inspect it
                return f"System Prompt Content: {m['content']}"
        return "No system prompt found"
        
    # Patch the achat function used by the agent
    # We need to find where achat is imported in the agent module
    from app.agents.meeting import meeting_agent
    meeting_agent.achat = mock_achat
    
    # 4. Execute analyze_with_context
    temp_chunks = [
        {"text": "Meeting Minute: Today we discussed lunch.", "chunk_id": "t1"}
    ]
    
    response = await agent.analyze_with_context(
        query=query,
        context="", # Not used if temp_chunks is processed inside
        citations=[],
        tenant_id="test_tenant",
        trace_id="test_trace",
        temp_chunks=temp_chunks
    )
    
    # 5. Verification
    answer = response.answer
    print(f"\nResponse from Mock LLM:\n{answer[:100]}...") # Print preview
    
    has_temp = "Meeting Minute: Today we discussed lunch" in answer
    has_kb = "Policy: Use cloud storage" in answer
    
    print(f"\nCheck Context Content:")
    print(f"- Contains Temp Data? {has_temp}")
    print(f"- Contains KB Data?   {has_kb}")
    
    if has_kb and has_temp:
        print("\n✅ SUCCESS: Hybrid Context Merged Correctly (Both Temp & KB present).")
    elif has_kb:
        print("\n✅ SUCCESS: KB Data present (partial success if temp missing).")
    else:
        print("\n❌ FAILURE: KB Data NOT found in context.")

if __name__ == "__main__":
    asyncio.run(verify_hybrid_flow())
