import asyncio
import sys
import os
from unittest.mock import MagicMock, AsyncMock, patch
from app.config import settings
from app.agents.accurate_people import AccuratePeopleAgent
from app.schemas.chat import ChatRequest

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../apps/backend/src")))

async def verify_agent_sql():
    # Configure for Shadow Mode
    settings.ENABLE_NEW_SQL_CORE = False
    settings.SQL_SHADOW_MODE = True
    print(f"ENABLE_NEW_SQL_CORE: {settings.ENABLE_NEW_SQL_CORE}")
    print(f"SQL_SHADOW_MODE: {settings.SQL_SHADOW_MODE}")
    
    # Mock route_query
    with patch("app.agents.accurate_people.route_query") as mock_route:
        mock_route.return_value = MagicMock(intent="LIST_LOOKUP", keywords=["Nam"])
        
        # Mock Legacy DB call
        with patch("app.core.db_sql.run_lookup_sql", new_callable=AsyncMock) as mock_legacy_run:
            mock_legacy_run.return_value = [
                {"data": {"full_name": "Nguyen Van Legacy", "occupation": "Legacy", "phone": "0111"}}
            ]
            
            # Mock get_async_db to yield a mock session
            mock_db = AsyncMock()
            with patch("app.core.db_sql.get_async_db") as mock_get_db:
                mock_get_db.return_value = iter([mock_db]) # Sync iterator for async for? No, async generator
                # Mocking async generator is tricky. Let's make it an async generator
                async def async_gen():
                    yield mock_db
                mock_get_db.side_effect = async_gen

                agent = AccuratePeopleAgent()
                
                # Mock Executor (Shadow)
                agent.executor = MagicMock()
                agent.executor.execute_safe = AsyncMock()
                agent.executor.execute_safe.return_value = {
                    "data": [
                        {"full_name": "Nguyen Van Shadow", "occupation": "Shadow", "phone": "0222"}
                    ]
                }
                
                agent.client = MagicMock()
                
                req = ChatRequest(message="tìm kiếm Nam", tenant_id="xa_demo", agent_id="accurate_people")
                
                print("Processing request...")
                res = await agent.process(req)
                
                print(f"Response: {res.answer}")
                
                # Verify Legacy Response
                if "Nguyen Van Legacy" in res.answer:
                    print("SUCCESS: Response came from Legacy Lane.")
                else:
                    print("FAILURE: Response did NOT come from Legacy Lane.")
                    sys.exit(1)
                
                # Verify Shadow Execution
                if agent.executor.execute_safe.called:
                    print("SUCCESS: Shadow SQL Executor was called.")
                    args, kwargs = agent.executor.execute_safe.call_args
                    print(f"Shadow SQL: {args[0]}")
                else:
                    print("FAILURE: Shadow SQL Executor NOT called.")
                    sys.exit(1)

if __name__ == "__main__":
    asyncio.run(verify_agent_sql())
