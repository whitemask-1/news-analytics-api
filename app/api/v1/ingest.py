from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional
import structlog  # type: ignore
from slowapi.util import get_remote_address
from slowapi import Limiter

from app.models.article import Article
from app.services.news_fetcher import NewsAPIError, NewsFetcher
from app.services.normalizer import ArticleNormalizer
from app.services.newsapi_quota_tracker import newsapi_quota_tracker


logger = structlog.get_logger()
router = APIRouter()  # Create a router instance

limiter = Limiter(key_func=get_remote_address)

class IngestRequest(BaseModel):
    """Request body for ingesting news articles"""
    query: str = Field(..., description="Search topic", min_length=1, max_length=100)
    limit: int = Field(default=10, ge=1, le=100, description="Max articles to fetch")
    language: str = Field(default="en", description="Language code (ISO 639-1)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "query": "climate change",
                "limit": 10,
                "language": "en"
            }
        }

class IngestResponse(BaseModel):
    """Response from the ingest endpoint"""
    status: str = Field(..., description="success or error")
    count: int = Field(..., description="Number of articles fetched")
    articles_preview: list[Article] = Field(
        default_factory=list,
        description="Sample of normalized articles (first 5)"
    )
    message: Optional[str] = Field(None, description="Additional info or error details")
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "count": 42,
                "articles_preview": [],
                "message": "Successfully normalized 42 articles"
            }
        }


# The ingest endpoint to fetch and normalize articles based on a search query
@router.post("/ingest", response_model=IngestResponse, tags=["Ingestion"])
@limiter.limit("10/minute") # Rate limit: 10 requests per minute per IP to prevent going over NewsAPI quotas
async def ingest_articles(body: IngestRequest, request: Request):
    logger.info("ingest_request_received", query=body.query, limit=body.limit, language=body.language, client_ip=request.client.host)
    fetcher = NewsFetcher()
    normalizer = ArticleNormalizer()

    if not newsapi_quota_tracker.check_and_increment():
        logger.error("newsapi_quota_exceeded", query=body.query)
        raise HTTPException(
            status_code=429,
            detail=f"Daily NewsAPI quota exceeded. Remaining: {newsapi_quota_tracker.get_remaining()}"
        )
    
    try:
        raw_articles = await fetcher.fetch_articles(
            query=body.query,
            limit=body.limit,
            language=body.language
        )

        if not raw_articles:
            logger.warning("no_articles_found", query=body.query)
            return IngestResponse(
                status="success",
                count=0,
                articles_preview=[],
                message= f"No articles found for the given query: '{body.query}'"
            )
        
        normalized_articles = normalizer.normalize_batch(
            raw_articles = raw_articles,
            source="newsapi",
            topic=body.query
        )

        if not normalized_articles:
            logger.error("normalization_failed_all", query=body.query, raw_count=len(raw_articles))
            raise HTTPException(status_code=500, detail="Failed to normalize any articles")
        
        preview = normalized_articles[:5]

        logger.info("ingest_success", 
                    query=body.query, 
                    fetched_count=len(raw_articles), 
                    normalized_count=len(normalized_articles))
        
        return IngestResponse(
            status="success",
            count=len(normalized_articles),
            articles_preview=preview,
            message=f"Successfully normalized {len(normalized_articles)} articles"
        )
        
    except NewsAPIError as e:
        logger.error("newsapi_error", error=str(e), query=body.query)
        raise HTTPException(status_code=502, detail=f"External API error: {str(e)}")
    
    except Exception as e:
        logger.error("unexpected_error", error=str(e), query=body.query, error_type=type(e).__name__)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
