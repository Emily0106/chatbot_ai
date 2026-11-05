from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.endpoints import router as api_router
from app.api.routes.admin import router as admin_router
from app.core.auth_context import require_internal_token

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(
    api_router,
    prefix=settings.API_V1_STR,
    dependencies=[Depends(require_internal_token)],
)
app.include_router(
    admin_router,
    prefix=f"{settings.API_V1_STR}/admin",
    tags=["admin"],
    dependencies=[Depends(require_internal_token)],
)

@app.get("/health")
def health_check():
    return {"status": "ok", "project": settings.PROJECT_NAME}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
