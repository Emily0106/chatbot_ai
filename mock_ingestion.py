from fastapi import FastAPI, Request
import uvicorn
import logging

app = FastAPI()
logger = logging.getLogger("uvicorn")

@app.post("/api/v1/ingest")
async def ingest(request: Request):
    data = await request.json()
    logger.info(f"Received ingestion request: {data}")
    return {"status": "queued", "message": "Mock ingestion successful"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)
