from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter() # Create a router instance

class HealthResponse(BaseModel):
    status: str
    version: str
    service: str

@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check(): #Health check endpoint for ALB target group health checks, ALB pings every 30 seconds for a 200 response
    return HealthResponse(
        status="ok", 
        version="1.0.0",
        service ="news-analytics-api"
    )

