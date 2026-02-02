from pydantic import BaseModel, HttpUrl, Field
from datetime import datetime
from typing import Optional

from app.models.article import Article
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
