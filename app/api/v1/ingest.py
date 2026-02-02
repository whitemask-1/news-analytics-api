from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional
import structlog  # type: ignore

from app.models.article import Article
from app.services.news_fetcher import NewsAPIError, NewsFetcher
from app.services.normalizer import ArticleNormalizer

logger = structlog.get_logger()
router = APIRouter()  # Create a router instance


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
@router.post("/ingest", response_model=IngestResponse, tags=["Ingest"])
async def ingest_articles(request: IngestRequest):
    fetcher = NewsFetcher()
    normalizer = ArticleNormalizer()
    
    try:
        raw_articles = await fetcher.fetch_articles(
            query=request.query,
            limit=request.limit,
            language=request.language
        )

        if not raw_articles:
            logger.warning("no_articles_found", query=request.query)
            return IngestResponse(
                status="success",
                count=0,
                articles_preview=[],
                message= f"No articles found for the given query: '{request.query}'"
            )
        
        normalized_articles = normalizer.normalize_batch(
            raw_articles = raw_articles,
            source="newsapi",
            topic=request.query
        )

        if not normalized_articles:
            logger.error("normalization_failed_all", query=request.query, raw_count=len(raw_articles))
            raise HTTPException(status_code=500, detail="Failed to normalize any articles")
        
        preview = normalized_articles[:5]

        logger.info("ingest_success", 
                    query=request.query, 
                    fetched_count=len(raw_articles), 
                    normalized_count=len(normalized_articles))
        
        return IngestResponse(
            status="success",
            count=len(normalized_articles),
            articles_preview=preview,
            message=f"Successfully normalized {len(normalized_articles)} articles"
        )
        
    except NewsAPIError as e:
        logger.error("newsapi_error", error=str(e), query=request.query)
        raise HTTPException(status_code=502, detail=f"External API error: {str(e)}")
    
    except Exception as e:
        logger.error("unexpected_error", error=str(e), query=request.query, error_type=type(e).__name__)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
