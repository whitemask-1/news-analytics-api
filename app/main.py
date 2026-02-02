from fastapi import FastAPI
from app.api.v1 import health, ingest

app = FastAPI(
    title="News Analytics API",
    description="Ingest, normalize, and analyze news from multiple sources",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Include routers
app.include_router(health.router, prefix="/api/v1", tags=["Health"])
app.include_router(ingest.router, prefix="/api/v1", tags=["Ingestion"])


@app.get("/", tags=["Root"])
async def root():
    """
    Root endpoint with API information.
    """
    return {
        "message": "News Analytics API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/api/v1/health",
        "endpoints": {
            "ingest": "POST /api/v1/ingest?query=<topic>",
            "health": "GET /api/v1/health"
        }
    }