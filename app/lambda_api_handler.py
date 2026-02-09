"""
Lambda API Handler for News Analytics API

This handler serves HTTP requests from API Gateway using FastAPI + Mangum.
Replaces the always-on ECS container with serverless Lambda.

Responsibilities:
- Health checks
- Accept ingest requests and publish to SQS (async processing)
- Serve analytics queries from Athena
- Return responses to API Gateway

Architecture:
API Gateway → Lambda (this handler) → SQS Queue → Worker Lambda

Benefits over ECS:
- Pay per request (vs. always-on container)
- Auto-scales 0-1000+ concurrent (vs. manual ECS scaling)
- No infrastructure management
- 50% cost reduction for low-traffic APIs

Cold Start:
- First request: ~1-2 seconds (FastAPI + imports)
- Warm requests: <100ms
- Mitigation: Provision concurrency if needed (costs extra)
"""

import json
import os
from datetime import datetime
from typing import Optional
import boto3
from mangum import Mangum
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
import structlog

# Import API routers
from app.api.v1 import health, analytics

# Import worker for local development mode
from app.lambda_worker_handler import process_single_message

# Initialize structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

# Create FastAPI app
app = FastAPI(
    title="News Analytics API",
    description="Serverless news article ingestion and analytics powered by Lambda",
    version="2.0.0",  # Version 2.0 = Lambda migration
    docs_url="/docs",
    redoc_url="/redoc"
)

# Include API routers
app.include_router(health.router, tags=["health"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["analytics"])

# =============================================================================
# SQS CLIENT (for publishing ingest requests)
# =============================================================================

# Initialize SQS client (reused across Lambda invocations)
_sqs_client = None

def get_sqs_client():
    """Get or create SQS client singleton."""
    global _sqs_client
    if _sqs_client is None:
        region = os.getenv("AWS_REGION_CUSTOM", "us-east-1")
        _sqs_client = boto3.client("sqs", region_name=region)
        logger.info("sqs_client_initialized", region=region)
    return _sqs_client


# =============================================================================
# REQUEST MODELS
# =============================================================================

class IngestRequest(BaseModel):
    """Request model for article ingestion."""
    
    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Search query for articles (e.g., 'artificial intelligence', 'climate change')"
    )
    
    limit: int = Field(
        default=100,
        ge=1,
        le=100,
        description="Maximum number of articles to fetch (1-100)"
    )
    
    language: str = Field(
        default="en",
        min_length=2,
        max_length=2,
        description="Language code (ISO 639-1, e.g., 'en', 'es', 'fr')"
    )
    
    @validator("query")
    def validate_query(cls, v):
        """Validate query is not empty or whitespace."""
        if not v or not v.strip():
            raise ValueError("Query cannot be empty")
        return v.strip()
    
    @validator("language")
    def validate_language(cls, v):
        """Convert language to lowercase."""
        return v.lower()


class IngestResponse(BaseModel):
    """Response model for ingest endpoint."""
    
    status: str = "accepted"
    message: str = Field(..., description="Status message")
    request_id: str = Field(..., description="SQS message ID for tracking")
    query: str = Field(..., description="Search query submitted")
    estimated_processing_time_seconds: int = Field(
        default=30,
        description="Estimated time for worker to process"
    )


# =============================================================================
# INGEST ENDPOINT
# =============================================================================

@app.post(
    "/api/v1/ingest",
    response_model=IngestResponse,
    status_code=202,
    summary="Ingest news articles",
    description="""
    Submit a request to fetch and process news articles.
    
    This endpoint is asynchronous:
    1. Validates request
    2. Publishes message to SQS queue
    3. Returns immediately (202 Accepted)
    4. Worker Lambda processes in background
    
    Processing includes:
    - Fetch from NewsAPI
    - Check Redis for duplicates
    - Normalize articles
    - Store to S3 (raw + normalized Parquet)
    
    Typical processing time: 10-60 seconds depending on article count.
    """
)
async def ingest_articles(request: IngestRequest):
    """
    Async article ingestion endpoint.
    
    Accepts ingest request, validates, and publishes to SQS for background processing.
    Worker Lambda will handle the actual fetching and processing.
    
    In LOCAL DEVELOPMENT mode (ENVIRONMENT=development), bypasses SQS and processes
    articles directly for easy testing without AWS infrastructure.
    
    Args:
        request: IngestRequest with query, limit, language
    
    Returns:
        IngestResponse with 202 Accepted status and message ID
    
    Example:
        >>> POST /api/v1/ingest
        >>> {
        >>>     "query": "artificial intelligence",
        >>>     "limit": 100,
        >>>     "language": "en"
        >>> }
        >>> 
        >>> Response (202 Accepted):
        >>> {
        >>>     "status": "accepted",
        >>>     "message": "Ingestion request queued for processing",
        >>>     "request_id": "abc123...",
        >>>     "query": "artificial intelligence"
        >>> }
    """
    try:
        logger.info(
            "ingest_request_received",
            query=request.query,
            limit=request.limit,
            language=request.language
        )
        
        # LOCAL DEVELOPMENT MODE: Process directly without SQS
        environment = os.getenv("ENVIRONMENT", "production")
        if environment == "development":
            logger.info("local_development_mode", message="Processing directly, bypassing SQS")
            
            # Prepare message payload
            message_body = {
                "query": request.query,
                "limit": request.limit,
                "language": request.language,
                "source": "api",
                "submitted_at": datetime.utcnow().isoformat()
            }
            
            # Process directly (synchronously for local testing)
            result = await process_single_message(message_body)
            
            return IngestResponse(
                status="completed",
                message=f"Articles processed successfully. Fetched: {result.get('fetched', 0)}, New: {result.get('new_articles', 0)}, Duplicates: {result.get('duplicates', 0)}",
                request_id="local-" + datetime.utcnow().strftime("%Y%m%d%H%M%S"),
                query=request.query,
                estimated_processing_time_seconds=0  # Already processed
            )
        
        # PRODUCTION MODE: Publish to SQS
        # Get SQS queue URL from environment
        queue_url = os.getenv("SQS_QUEUE_URL")
        if not queue_url:
            logger.error("sqs_queue_url_not_configured")
            raise HTTPException(
                status_code=500,
                detail="SQS queue not configured. Set ENVIRONMENT=development for local testing or configure SQS_QUEUE_URL for production."
            )
        
        # Prepare message payload (flexible JSON structure for worker)
        message_body = {
            "query": request.query,
            "limit": request.limit,
            "language": request.language,
            "source": "api",  # Track if from API or scheduled
            "submitted_at": datetime.utcnow().isoformat()
        }
        
        # Publish to SQS
        sqs = get_sqs_client()
        response = sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(message_body),
            MessageAttributes={
                "query": {
                    "StringValue": request.query[:100],  # Truncate for attribute limit
                    "DataType": "String"
                },
                "source": {
                    "StringValue": "api",
                    "DataType": "String"
                }
            }
        )
        
        message_id = response["MessageId"]
        
        logger.info(
            "ingest_request_queued",
            message_id=message_id,
            query=request.query
        )
        
        return IngestResponse(
            message=f"Ingestion request queued for processing",
            request_id=message_id,
            query=request.query,
            estimated_processing_time_seconds=30
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "ingest_request_failed",
            query=request.query,
            error=str(e)
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to queue ingestion request: {str(e)}"
        )


# =============================================================================
# ROOT ENDPOINT
# =============================================================================

@app.get(
    "/",
    summary="API Information",
    description="Get API metadata and available endpoints"
)
async def root():
    """
    API information endpoint.
    
    Returns metadata about the API, version, and available endpoints.
    Useful for API discovery and health monitoring.
    """
    return {
        "name": "News Analytics API",
        "version": "2.0.0",
        "description": "Serverless news article ingestion and analytics",
        "architecture": "Lambda + SQS + S3 + Athena",
        "endpoints": {
            "health": "/health",
            "ingest": "POST /api/v1/ingest",
            "analytics_counts": "GET /api/v1/analytics/counts",
            "analytics_trending": "GET /api/v1/analytics/trending",
            "analytics_sources": "GET /api/v1/analytics/sources",
            "docs": "/docs",
            "redoc": "/redoc"
        },
        "migration_info": {
            "previous_architecture": "ECS Fargate",
            "migration_reason": "Cost reduction (50%), auto-scaling, serverless benefits",
            "cost_savings": "$12-20/month"
        }
    }


# =============================================================================
# ERROR HANDLERS
# =============================================================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Global exception handler for uncaught errors.
    
    Logs error and returns 500 response.
    Prevents Lambda from crashing on unexpected errors.
    """
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        exc_info=True
    )
    
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "message": "Internal server error",
            "detail": str(exc) if os.getenv("ENVIRONMENT") == "dev" else "An error occurred"
        }
    )


# =============================================================================
# LAMBDA HANDLER
# =============================================================================

# Mangum adapter: Converts API Gateway events to ASGI (FastAPI) format
# This is the magic that makes FastAPI work in Lambda
handler = Mangum(
    app,
    lifespan="off",  # Disable lifespan events (not needed in Lambda)
    api_gateway_base_path="/",  # Base path for API Gateway
)


# Lambda handler function (entry point)
# API Gateway → Lambda Runtime → handler() → Mangum → FastAPI → response
def lambda_handler(event, context):
    """
    AWS Lambda handler function.
    
    This is the entry point when API Gateway invokes the Lambda.
    Mangum handles the event conversion and routing to FastAPI.
    
    Args:
        event: API Gateway event (HTTP request)
        context: Lambda context (metadata about invocation)
    
    Returns:
        API Gateway response (HTTP response)
    """
    # Log invocation for debugging
    logger.info(
        "lambda_invocation",
        request_id=context.request_id,
        function_name=context.function_name,
        remaining_time_ms=context.get_remaining_time_in_millis(),
        path=event.get("rawPath", "unknown"),
        method=event.get("requestContext", {}).get("http", {}).get("method", "unknown")
    )
    
    # Call Mangum handler
    response = handler(event, context)
    
    logger.info(
        "lambda_response",
        request_id=context.request_id,
        status_code=response.get("statusCode", 0)
    )
    
    return response
