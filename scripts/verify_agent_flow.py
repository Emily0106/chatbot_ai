import sys
import os
import asyncio
import logging

# Ensure app is in path
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), "apps/backend/src"))
sys.path.append(os.path.join(os.getcwd(), "libs/core_shared"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VERIFY")

from app.agents.contract import TrustedContext, AgentResponse
from app.agents.base import BaseAgent
# Import the global registry and initialization function
from app.agents.registry import registry, register_defaults, get_agent

async def main():
    logger.info("Initializing AgentRegistry (Defaults)...")
    try:
        register_defaults()
    except Exception as e:
        logger.warning(f"register_defaults failure: {e}")
        import traceback
        traceback.print_exc()

    # MOCK LLM for CI/Offline safety
    from unittest.mock import patch, AsyncMock
    
    # Patch `achat` and `generate_text` to return dummy content
    mock_achat = AsyncMock(return_value="[MOCK] Wrapper answer for verification.")
    mock_gen_text = AsyncMock(return_value="[MOCK] Generated text.")
    
    # Ensure nested calls (like aextract_pydantic) don't crash usage of client
    # We patch at module level to catch all agents
    with patch("app.core.llm_client.achat", mock_achat), \
         patch("app.core.llm_client.generate_text", mock_gen_text):

        ids = list(registry.list_agents().keys())
        logger.info(f"Registered Agents: {ids}")
        
        # Test Citizen Agent - Process
        if "citizen" in ids:
            logger.info("Testing Citizen Agent process()...")
        citizen = get_agent("citizen")
        
        ctx = TrustedContext(
            tenant_id="default",
            user_id="verifier",
            security_level=1,
            geo_code="00",
            department_id="gov_public",
            request_payload={}
        )
        
        try:
            resp = await citizen.process(ctx, "Thu tuc cap lai CCCD?")
            logger.info(f"Citizen Response: {resp.answer[:50]}...")
            if not resp.answer and resp.meta.get("refusal"):
                 logger.info("Citizen refused (likely no docs), which is VALID flow.")
            elif not resp.answer:
                logger.error("Citizen returned empty answer without refusal")
                sys.exit(1)
        except Exception as e:
            logger.error(f"Citizen process failed: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

    # Test Legal Agent - Process (RAG)
    if "legal" in ids:
        logger.info("Testing Legal Agent process()...")
        legal = get_agent("legal")
        
        ctx_legal = TrustedContext(
            tenant_id="default",
            user_id="verifier",
            security_level=1,
            geo_code="00",
            department_id="gov_legal",
            request_payload={"filters": {"doc_type": "law"}}
        )
        
        try:
            resp = await legal.process(ctx_legal, "Luat dat dai 2024?")
            logger.info(f"Legal Response: {resp.answer[:50]}...")
        except Exception as e:
            logger.error(f"Legal process failed: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
            
    # Test AccuratePeople Agent - Process (Stub)
    if "accurate_people" in ids:
        logger.info("Testing AccuratePeople Agent process()...")
        acc_agent = get_agent("accurate_people")
        
        valid_payload = {
            "agent_id": "accurate_people",
            "message": "Tim ong A", 
            "tenant_id": "default"
        }
        
        acc_ctx = TrustedContext(
            tenant_id="default",
            user_id="verifier",
            security_level=1,
            request_payload=valid_payload
        )
        
        try:
            resp = await acc_agent.process(acc_ctx, "Tim ong A")
            logger.info(f"AccuratePeople Response: {resp.answer[:50]}...")
        except Exception as e:
            logger.error(f"AccuratePeople process failed: {e}")
            # We want it to pass, so exit if fail (but allow 404 from Qdrant if collection missing)
            if "collection" in str(e).lower() or "not found" in str(e).lower():
                logger.warning("AccuratePeople failed on known Qdrant 404 (Expected if no data).")
            else:
                sys.exit(1)

        logger.info("Verificaton PASSED")

if __name__ == "__main__":
    asyncio.run(main())
