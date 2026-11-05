#!/usr/bin/env python3
import os
import sys
import subprocess

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _run(name: str, timeout_s: int = 30) -> None:
    path = os.path.join(REPO_ROOT, "scripts", name)
    env = os.environ.copy()
    env.setdefault("APP_MODE", "offline")
    env.setdefault("CI_MODE", "true")
    env.setdefault("ENV_MODE", "dev")
    print(f"\n--- RUN: {name} ---")
    subprocess.run([sys.executable, path], env=env, check=True, timeout=timeout_s)

def main() -> int:
    print("=" * 60)
    print("🛡️  SECURITY E2E INTEGRATION TEST SUITE (THE GAUNTLET)")
    print("=" * 60)

    for i in (1, 2):
        print(f"\n==================== PASS {i}/2 ====================")
        try:
            _run("verify_ingestion_security_e2e.py", timeout_s=30)
            _run("verify_backend_security_e2e.py", timeout_s=30)
            print(f"✅✅✅ PASS {i}/2 complete")
        except subprocess.TimeoutExpired:
            print(f"❌ FAIL: Test timed out in pass {i}")
            return 1
        except subprocess.CalledProcessError:
            print(f"❌ FAIL: Test failed in pass {i}")
            return 1
            
    print("\n" + "=" * 60)
    print("🎉 SUPER TEST COMPLETE!")
    print("=" * 60)
    print("✅ All security checks passed twice consecutively")
    print("✅ No flakiness detected")
    print("✅ Safe to commit and deploy")
    print("=" * 60)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
