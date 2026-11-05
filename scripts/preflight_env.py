#!/usr/bin/env python3
"""
Preflight Environment Validation Script

Validates environment configuration before deployment.
Complements C0 runtime validation by catching errors BEFORE docker compose up.

Usage:
    python3 scripts/preflight_env.py
    python3 scripts/preflight_env.py --env-mode staging
    python3 scripts/preflight_env.py --verbose

Exit Codes:
    0: All checks passed
    1: One or more checks failed
"""

import argparse
import json
import os
import sys
from typing import Dict, List, Tuple

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    RESET = '\033[0m'

def mask_secret(value: str, show_chars: int = 4) -> str:
    """Mask a secret value, showing only first/last few characters"""
    if not value or len(value) <= show_chars * 2:
        return "***"
    return f"{value[:show_chars]}...{value[-show_chars:]}"

def check_env_var(name: str, required: bool = True, mask: bool = False) -> Tuple[bool, str]:
    """Check if environment variable exists"""
    value = os.getenv(name, "")
    
    if not value:
        if required:
            return False, f"❌ {name}: Missing (required)"
        else:
            return True, f"⚠️  {name}: Not set (optional)"
    
    if mask:
        display = mask_secret(value)
    else:
        display = value[:50] + "..." if len(value) > 50 else value
    
    return True, f"✅ {name}: Present ({display})"

def check_api_keys_json(value: str) -> Tuple[bool, str]:
    """Validate API_KEYS_JSON format"""
    if not value:
        return False, "❌ API_KEYS_JSON: Missing (required in staging/prod)"
    
    try:
        keys = json.loads(value)
        if not isinstance(keys, dict):
            return False, "❌ API_KEYS_JSON: Must be a JSON object"
        
        if len(keys) == 0:
            return False, "❌ API_KEYS_JSON: Must contain at least one key"
        
        # Validate format
        for key, val in keys.items():
            if not isinstance(key, str):
                return False, "❌ API_KEYS_JSON: Invalid format (key must be string)"
                
            # C3.1: Value can be dict (claims) or string (tenant_id)
            if isinstance(val, dict):
                # Allow 'role' (legacy) or 'roles' (RBAC)
                if "tenant_id" not in val or ("role" not in val and "roles" not in val):
                    return False, f"❌ API_KEYS_JSON: Key '{key[:4]}...' missing tenant_id or role/roles in claims"
            elif isinstance(val, str):
                pass # Legacy format
            else:
                 return False, "❌ API_KEYS_JSON: Invalid format (value must be string or dict)"

            if len(key) < 10: # Relaxed slightly for test keys
                return False, f"❌ API_KEYS_JSON: Key too short (minimum 10 chars, got {len(key)})"
        
        return True, f"✅ API_KEYS_JSON: Valid ({len(keys)} key(s))"
    except json.JSONDecodeError as e:
        return False, f"❌ API_KEYS_JSON: Invalid JSON - {str(e)}"

def check_db_url(value: str, env_mode: str) -> Tuple[bool, str]:
    """Check database URL"""
    if not value:
        return False, "❌ DB_URL: Missing"
    
    # Check for dev/CI defaults in staging/prod
    if env_mode in ["staging", "prod"]:
        dev_patterns = ["postgres:postgres@", "test:test@", "localhost", "postgres:5432"]
        if any(pattern in value for pattern in dev_patterns):
            return False, f"❌ DB_URL: Using dev/CI default in {env_mode.upper()} (not allowed)"
    
    # Mask password in URL
    masked = value.split("@")[0].split("://")[0] + "://***@" + value.split("@")[1] if "@" in value else "***"
    return True, f"✅ DB_URL: Present ({masked[:50]}...)"

def check_url(name: str, value: str, env_mode: str, dev_defaults: List[str]) -> Tuple[bool, str]:
    """Check URL configuration"""
    if not value:
        return False, f"❌ {name}: Missing"
    
    # Check for dev/CI defaults in staging/prod
    if env_mode in ["staging", "prod"]:
        if any(default in value for default in dev_defaults):
            return False, f"❌ {name}: Using dev/CI default in {env_mode.upper()} (not allowed)"
    
    return True, f"✅ {name}: Present ({value[:50]}...)"

def validate_environment(env_mode: str = None, verbose: bool = False) -> Tuple[bool, List[str]]:
    """
    Validate environment configuration.
    Returns: (all_passed, messages)
    """
    messages = []
    checks_passed = []
    
    # Get ENV_MODE
    if not env_mode:
        env_mode = os.getenv("ENV_MODE", "dev").lower()
    
    messages.append(f"{Colors.BLUE}{Colors.BOLD}Environment Mode: {env_mode.upper()}{Colors.RESET}\n")
    
    # Basic environment checks
    ci_mode = os.getenv("CI_MODE", "false").lower() in ("true", "1", "yes")
    
    # Check 1: CI_MODE in staging/prod
    if env_mode in ["staging", "prod"] and ci_mode:
        passed = False
        msg = f"❌ CI_MODE: Cannot be enabled in {env_mode.upper()}"
        checks_passed.append(passed)
        messages.append(msg)
    else:
        passed = True
        msg = f"✅ CI_MODE: Correct (false in {env_mode.upper()})" if env_mode in ["staging", "prod"] else "✅ CI_MODE: OK"
        checks_passed.append(passed)
        messages.append(msg)
    
    # For dev/ci, validation is relaxed
    if env_mode in ["dev", "ci"]:
        messages.append(f"\n{Colors.YELLOW}Dev/CI mode - relaxed validation{Colors.RESET}")
        
        # Just check basic vars exist
        passed, msg = check_env_var("DB_URL", required=False)
        checks_passed.append(passed)
        messages.append(msg)
        
        passed, msg = check_env_var("QDRANT_URL", required=False)
        checks_passed.append(passed)
        messages.append(msg)
        
        passed, msg = check_env_var("OPENAI_API_KEY", required=False, mask=True)
        checks_passed.append(passed)
        messages.append(msg)
        
        return all(checks_passed), messages
    
    # Staging/Prod: Strict validation
    messages.append(f"\n{Colors.BOLD}Required Secrets:{Colors.RESET}")
    
    # Check 2: API_KEYS_JSON
    api_keys_json = os.getenv("API_KEYS_JSON", "")
    passed, msg = check_api_keys_json(api_keys_json)
    checks_passed.append(passed)
    messages.append(msg)
    
    # Check 3: ALLOW_DEFAULT_TENANT
    allow_default = os.getenv("ALLOW_DEFAULT_TENANT", "false").lower() in ("true", "1", "yes")
    migration_mode = os.getenv("MIGRATION_MODE", "false").lower() in ("true", "1", "yes")
    
    if allow_default and not migration_mode:
        passed = False
        msg = f"❌ ALLOW_DEFAULT_TENANT: Cannot be enabled in {env_mode.upper()} (unless MIGRATION_MODE=true)"
        checks_passed.append(passed)
        messages.append(msg)
    else:
        passed = True
        msg = "✅ ALLOW_DEFAULT_TENANT: Correct (false)"
        checks_passed.append(passed)
        messages.append(msg)
    
    # Check 4: Database
    messages.append(f"\n{Colors.BOLD}Infrastructure:{Colors.RESET}")
    
    db_url = os.getenv("DB_URL", "")
    passed, msg = check_db_url(db_url, env_mode)
    checks_passed.append(passed)
    messages.append(msg)
    
    # Check 5: Qdrant
    qdrant_url = os.getenv("QDRANT_URL", "")
    passed, msg = check_url("QDRANT_URL", qdrant_url, env_mode, ["localhost:6333"])
    checks_passed.append(passed)
    messages.append(msg)
    
    # Check 6: Redis
    redis_url = os.getenv("REDIS_URL", "")
    passed, msg = check_url("REDIS_URL", redis_url, env_mode, ["localhost:6379"])
    checks_passed.append(passed)
    messages.append(msg)
    
    # Check 7: OpenAI API Key (if needed)
    messages.append(f"\n{Colors.BOLD}LLM Configuration:{Colors.RESET}")
    
    embedding_backend = os.getenv("EMBEDDING_BACKEND", "local").lower()
    openai_key = os.getenv("OPENAI_API_KEY", "")
    
    # In prod, always require OpenAI key
    # In staging, require if using OpenAI backend
    requires_openai = env_mode == "prod" or embedding_backend == "openai"
    
    if requires_openai:
        if not openai_key or openai_key in ["dummy", "mock", "your-openai-api-key-here"]:
            passed = False
            msg = f"❌ OPENAI_API_KEY: Missing or using placeholder in {env_mode.upper()}"
            checks_passed.append(passed)
            messages.append(msg)
        else:
            passed = True
            msg = f"✅ OPENAI_API_KEY: Present ({mask_secret(openai_key)})"
            checks_passed.append(passed)
            messages.append(msg)
    else:
        messages.append(f"⚠️  OPENAI_API_KEY: Not required (EMBEDDING_BACKEND={embedding_backend})")
    
    return all(checks_passed), messages

def main():
    parser = argparse.ArgumentParser(description="Preflight Environment Validation")
    parser.add_argument("--env-mode", help="Override ENV_MODE (default: from environment)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}{Colors.BOLD}Gov-AI Backend - Preflight Environment Validation{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}\n")
    
    all_passed, messages = validate_environment(args.env_mode, args.verbose)
    
    for msg in messages:
        print(msg)
    
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    
    if all_passed:
        print(f"{Colors.GREEN}{Colors.BOLD}✅ ALL CHECKS PASSED{Colors.RESET}")
        print(f"{Colors.GREEN}Environment is ready for deployment{Colors.RESET}")
        return 0
    else:
        print(f"{Colors.RED}{Colors.BOLD}❌ VALIDATION FAILED{Colors.RESET}")
        print(f"{Colors.RED}Fix the errors above before deploying{Colors.RESET}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
