import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from app.core.sql.generator import SQLGenerator

async def main():
    print("Initializing SQLGenerator...")
    try:
        generator = SQLGenerator()
        
        query = "Thống kê tổng thu ngân sách năm 2024"
        print(f"\nTesting with query: '{query}'")
        
        result = await generator.generate(query)
        
        print("\n--- Result ---")
        print(result)
        
        if "sql" in result and "params" in result:
            print("\n✅ Verification Passed: Valid JSON with SQL and Params.")
        else:
            print("\n❌ Verification Failed: Missing keys in response.")
            
    except Exception as e:
        print(f"\n❌ Verification Failed with error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
