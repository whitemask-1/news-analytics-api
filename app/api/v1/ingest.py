from pydantic import BaseModel, HttpUrl, Field
from datetime import datetime
from typing import Optional

class Article(BaseModel):  # All incoming data must conform to this schema of article

    source: str = Field(..., description="News provider (newsapi, guardian, nytimes)")
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = Field(None, max_length=2000)
    url: HttpUrl  # Pydantic automatically validates URL format
    published_at: datetime
    topic: Optional[str] = Field(None, description="Search query that found this article")

    class Config: # Example for API documentation
        json_schema_extra = {
            "example": {
                "source": "newsapi",
                "title": "Climate Summit Reaches Historic Agreement",
                "description": "World leaders commit to new emission reduction targets",
                "url": "https://example.com/article",
                "published_at": "2026-02-01T14:30:00Z",
                "topic": "climate change"
            }
        }

class IngestRequest(BaseModel): #Request parameters for the ingest endpoint
    query: str = Field(..., description="Search topic", min_length=1)
    limit: int = Field(default=10, ge=1, le=100, description="Max articles to fetch")

class IngestResponse(BaseModel): #Response model from the ingest endpoint
    status: str = Field(..., description="success or error")
    count: int = Field(..., description="Number of articles fetched")
    articles_preview: list[Article] = Field(
        default_factory=list,
        description="Sample of normalized articles (first 5)"
    )
    message: Optional[str] = Field(None, description="Additional info or error details")
