"""
Analytics API Endpoints

Provides HTTP endpoints for querying news article analytics using Athena.
All queries run against S3-stored Parquet data with automatic partition pruning.

Endpoints:
- GET /analytics/counts - Article counts grouped by source/topic/day
- GET /analytics/trending - Trending topics by article frequency  
- GET /analytics/sources - Source/publisher distribution statistics

Rate Limits:
- 20 requests/minute per IP (Athena queries can be expensive)
- Consider caching results on client side

Cost Optimization:
- Queries use partition pruning (only scan relevant date ranges)
- Results cached in Athena for 24 hours
- Average cost: $0.001-0.01 per query
"""

from datetime import date, timedelta
from typing import Optional, Literal
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
import structlog

from app.services.athena import get_athena_service

# Initialize router and logger
router = APIRouter()
logger = structlog.get_logger(__name__)


# =============================================================================
# RESPONSE MODELS
# =============================================================================

class ArticleCountItem(BaseModel):
    """Single article count result."""
    group_value: str = Field(..., description="Value of the grouped field (source, topic, etc.)")
    count: int = Field(..., description="Number of articles")


class ArticleCountsResponse(BaseModel):
    """Response model for article counts endpoint."""
    status: str = "success"
    start_date: str = Field(..., description="Query start date (YYYY-MM-DD)")
    end_date: str = Field(..., description="Query end date (YYYY-MM-DD)")
    group_by: str = Field(..., description="Grouping field (source/topic/day)")
    results: list[dict] = Field(..., description="Count results")
    total_results: int = Field(..., description="Number of result rows")
    execution_time_ms: int = Field(..., description="Athena query execution time")


class TrendingTopicItem(BaseModel):
    """Single trending topic result."""
    topic: str = Field(..., description="Topic/query term")
    count: int = Field(..., description="Number of articles")
    sources: int = Field(..., description="Number of unique sources covering this topic")


class TrendingTopicsResponse(BaseModel):
    """Response model for trending topics endpoint."""
    status: str = "success"
    days: int = Field(..., description="Number of days analyzed")
    results: list[dict] = Field(..., description="Trending topics")
    total_results: int = Field(..., description="Number of topics returned")
    execution_time_ms: int = Field(..., description="Athena query execution time")


class SourceDistributionItem(BaseModel):
    """Single source distribution result."""
    source: str = Field(..., description="Article source (newsapi, guardian, etc.)")
    publishers: int = Field(..., description="Number of unique publishers")
    articles: int = Field(..., description="Total articles from this source")
    oldest: Optional[str] = Field(None, description="Oldest article timestamp")
    newest: Optional[str] = Field(None, description="Newest article timestamp")


class SourceDistributionResponse(BaseModel):
    """Response model for source distribution endpoint."""
    status: str = "success"
    results: list[dict] = Field(..., description="Source distribution statistics")
    total_sources: int = Field(..., description="Number of sources")
    execution_time_ms: int = Field(..., description="Athena query execution time")


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get(
    "/counts",
    response_model=ArticleCountsResponse,
    summary="Get article counts",
    description="""
    Get article counts grouped by specified field.
    
    Uses efficient partition pruning on date range to minimize costs.
    Average cost: $0.001-0.005 per query.
    
    Examples:
    - /analytics/counts?group_by=source - Count by source
    - /analytics/counts?group_by=topic&start_date=2026-02-01 - Topics in February
    - /analytics/counts?group_by=day&days=30 - Daily counts for last 30 days
    """,
    tags=["analytics"]
)
async def get_article_counts(
    group_by: Literal["source", "source_name", "topic", "day"] = Query(
        "source",
        description="Field to group by: source (API), source_name (publisher), topic, or day"
    ),
    start_date: Optional[str] = Query(
        None,
        description="Start date (YYYY-MM-DD). Defaults to 7 days ago."
    ),
    end_date: Optional[str] = Query(
        None,
        description="End date (YYYY-MM-DD). Defaults to today."
    ),
    days: Optional[int] = Query(
        None,
        description="Alternative to start_date: specify number of days to look back"
    )
):
    """
    Get article counts grouped by source, publisher, topic, or day.
    
    Query Parameters:
        - group_by: What to group by (source, source_name, topic, day)
        - start_date: YYYY-MM-DD format (overrides days parameter)
        - end_date: YYYY-MM-DD format
        - days: Number of days to look back (simpler than specifying dates)
    
    Returns:
        ArticleCountsResponse with counts and metadata
    
    Examples:
        >>> GET /analytics/counts?group_by=source
        >>> # Returns article counts by source for last 7 days
        >>> 
        >>> GET /analytics/counts?group_by=day&days=30
        >>> # Returns daily article counts for last 30 days
    """
    try:
        # Calculate date range
        if days is not None and start_date is None:
            # Use days parameter to calculate start_date
            end_date = end_date or date.today().isoformat()
            start_date = (date.today() - timedelta(days=days)).isoformat()
        
        logger.info(
            "analytics_counts_request",
            group_by=group_by,
            start_date=start_date,
            end_date=end_date
        )
        
        # Execute Athena query
        athena = get_athena_service()
        result = await athena.get_article_counts(
            start_date=start_date,
            end_date=end_date,
            group_by=group_by
        )
        
        # Use actual dates from query (defaults applied in athena service)
        actual_start = start_date or (date.today() - timedelta(days=7)).isoformat()
        actual_end = end_date or date.today().isoformat()
        
        response = ArticleCountsResponse(
            start_date=actual_start,
            end_date=actual_end,
            group_by=group_by,
            results=result,
            total_results=len(result),
            execution_time_ms=0  # TODO: Get from athena result
        )
        
        logger.info(
            "analytics_counts_success",
            group_by=group_by,
            result_count=len(result)
        )
        
        return response
        
    except Exception as e:
        logger.error(
            "analytics_counts_error",
            group_by=group_by,
            error=str(e)
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to execute analytics query: {str(e)}"
        )


@router.get(
    "/trending",
    response_model=TrendingTopicsResponse,
    summary="Get trending topics",
    description="""
    Get most common topics by article frequency.
    
    Identifies trending news subjects based on how many articles mention them.
    Useful for understanding what topics are getting the most coverage.
    
    Average cost: $0.001-0.005 per query.
    
    Examples:
    - /analytics/trending - Top 20 topics in last 7 days
    - /analytics/trending?days=3&limit=10 - Top 10 topics in last 3 days
    """,
    tags=["analytics"]
)
async def get_trending_topics(
    days: int = Query(
        7,
        ge=1,
        le=90,
        description="Number of days to analyze (1-90)"
    ),
    limit: int = Query(
        20,
        ge=1,
        le=100,
        description="Maximum number of topics to return (1-100)"
    )
):
    """
    Get trending topics by article frequency.
    
    Analyzes recent articles to find most common topics.
    Returns topics sorted by number of articles.
    
    Query Parameters:
        - days: How many days to look back (default: 7, max: 90)
        - limit: Maximum topics to return (default: 20, max: 100)
    
    Returns:
        TrendingTopicsResponse with topics sorted by frequency
    
    Examples:
        >>> GET /analytics/trending?days=3&limit=10
        >>> # Returns top 10 trending topics in last 3 days
        >>> 
        >>> GET /analytics/trending
        >>> # Returns top 20 topics in last 7 days (defaults)
    """
    try:
        logger.info(
            "analytics_trending_request",
            days=days,
            limit=limit
        )
        
        # Execute Athena query
        athena = get_athena_service()
        result = await athena.get_trending_topics(days=days, limit=limit)
        
        response = TrendingTopicsResponse(
            days=days,
            results=result,
            total_results=len(result),
            execution_time_ms=0  # TODO: Get from athena result
        )
        
        logger.info(
            "analytics_trending_success",
            days=days,
            result_count=len(result)
        )
        
        return response
        
    except Exception as e:
        logger.error(
            "analytics_trending_error",
            days=days,
            limit=limit,
            error=str(e)
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to execute trending query: {str(e)}"
        )


@router.get(
    "/sources",
    response_model=SourceDistributionResponse,
    summary="Get source distribution",
    description="""
    Get article distribution across sources and publishers.
    
    Shows which news sources provide the most content and data diversity.
    Useful for understanding data source coverage.
    
    Average cost: $0.001-0.003 per query.
    
    Example:
    - /analytics/sources - All sources with statistics
    """,
    tags=["analytics"]
)
async def get_source_distribution():
    """
    Get distribution of articles across sources and publishers.
    
    Returns statistics for each news source:
    - Number of unique publishers
    - Total articles
    - Date range of articles
    
    Returns:
        SourceDistributionResponse with source statistics
    
    Examples:
        >>> GET /analytics/sources
        >>> # Returns statistics for all sources
    """
    try:
        logger.info("analytics_sources_request")
        
        # Execute Athena query
        athena = get_athena_service()
        result = await athena.get_source_distribution()
        
        response = SourceDistributionResponse(
            results=result,
            total_sources=len(result),
            execution_time_ms=0  # TODO: Get from athena result
        )
        
        logger.info(
            "analytics_sources_success",
            source_count=len(result)
        )
        
        return response
        
    except Exception as e:
        logger.error(
            "analytics_sources_error",
            error=str(e)
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to execute source distribution query: {str(e)}"
        )
