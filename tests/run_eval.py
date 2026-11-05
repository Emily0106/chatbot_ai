import asyncio
import json
import os
import sys
import time
from typing import List, Dict, Any
import logging

# Add project root to path
sys.path.append(os.getcwd())

from app.core.sql.generator import SQLGenerator, GenerationError
from app.core.sql.validator import SQLValidator
from app.core.sql.types import SQLPolicy, SecurityError, ValidationError

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def run_eval():
    dataset_path = "tests/data/golden_sql_dataset.jsonl"
    output_path = "tests/eval_results.json"
    
    if not os.path.exists(dataset_path):
        logger.error(f"Dataset not found at {dataset_path}")
        return

    logger.info("Initializing Generator and Validator...")
    generator = SQLGenerator()
    validator = SQLValidator()
    
    # Default policy for validation
    policy = SQLPolicy(
        tenant_column="commune_id",
        allowed_relations=["view_people", "view_budget", "structured_rows"],
        max_limit=50,
        statement_timeout_ms=2000,
        forbid_set_ops=True,
        forbid_subquery=False,
        forbid_join=False
    )
    tenant_id = "eval_test"

    results = []
    total_questions = 0
    valid_count = 0
    total_latency = 0
    
    logger.info("Starting Evaluation...")
    
    with open(dataset_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        total_questions = len(lines)
        
        for i, line in enumerate(lines):
            if not line.strip():
                continue
                
            record = json.loads(line)
            question = record["question"]
            expected_sql = record["sql"]
            difficulty = record.get("difficulty", "unknown")
            
            logger.info(f"[{i+1}/{total_questions}] Processing: {question}")
            
            start_time = time.perf_counter()
            generated_sql = None
            generated_params = {}
            error_msg = None
            is_valid = False
            
            try:
                # 1. Generate
                gen_result = await generator.generate(question)
                generated_sql = gen_result.get("sql")
                generated_params = gen_result.get("params", {})
                
                # 2. Validate
                if generated_sql:
                    validator.validate_and_transform(
                        raw_sql=generated_sql,
                        params=generated_params,
                        tenant_id=tenant_id,
                        policy=policy,
                        lane="template"
                    )
                    is_valid = True
                else:
                    error_msg = "No SQL generated"

            except (SecurityError, ValidationError) as e:
                error_msg = f"Validation Failed: {str(e)}"
            except GenerationError as e:
                error_msg = f"Generation Failed: {str(e)}"
            except Exception as e:
                error_msg = f"System Error: {str(e)}"
            
            latency_ms = (time.perf_counter() - start_time) * 1000
            total_latency += latency_ms
            
            if is_valid:
                valid_count += 1
                logger.info(f"  ✅ PASS ({latency_ms:.2f}ms)")
            else:
                logger.warning(f"  ❌ FAIL ({latency_ms:.2f}ms): {error_msg}")
                logger.warning(f"     Generated: {generated_sql}")

            results.append({
                "question": question,
                "expected_sql": expected_sql,
                "generated_sql": generated_sql,
                "generated_params": generated_params,
                "difficulty": difficulty,
                "is_valid": is_valid,
                "error": error_msg,
                "latency_ms": latency_ms
            })

    # Summary
    valid_rate = (valid_count / total_questions) * 100 if total_questions > 0 else 0
    avg_latency = total_latency / total_questions if total_questions > 0 else 0
    
    summary = {
        "total_questions": total_questions,
        "valid_count": valid_count,
        "valid_rate": valid_rate,
        "avg_latency_ms": avg_latency,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Save results
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "details": results}, f, ensure_ascii=False, indent=2)
        
    print("\n" + "="*30)
    print("EVALUATION SUMMARY")
    print("="*30)
    print(f"Total Questions: {total_questions}")
    print(f"Valid SQL:       {valid_count}")
    print(f"Valid Rate:      {valid_rate:.2f}%")
    print(f"Avg Latency:     {avg_latency:.2f}ms")
    print("="*30)
    print(f"Detailed results saved to {output_path}")

if __name__ == "__main__":
    asyncio.run(run_eval())
