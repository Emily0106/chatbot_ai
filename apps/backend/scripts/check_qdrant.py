import asyncio
from qdrant_client import AsyncQdrantClient

async def main():
    client = AsyncQdrantClient(location=":memory:")
    print(f"Has search: {hasattr(client, 'search')}")
    print(f"Has query_points: {hasattr(client, 'query_points')}")
    print(f"Has retrieve: {hasattr(client, 'retrieve')}")
    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
