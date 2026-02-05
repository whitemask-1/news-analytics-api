from datetime import datetime
from typing import Optional
from pydantic import BaseModel, HttpUrl, Field
import hashlib

class Article(BaseModel):  # All incoming data must conform to this schema of article

    source: str = Field(..., description="News provider (newsapi, guardian, nytimes)")
    source_name: str = Field(..., description="Specific publication name")
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = Field(None, max_length=2000)
    url: HttpUrl  # Pydantic automatically validates URL format
    published_at: datetime
    topic: Optional[str] = Field(None, description="Search query that found this article")
    article_hash: Optional[str] = Field(None, description="Unique hash for deduplication")

    class Config: # Example for API documentation
        json_schema_extra = {
            "example": {
                "source": "newsapi",
                "source_name": "bbcnews",
                "title": "Climate Summit Reaches Historic Agreement",
                "description": "World leaders commit to new emission reduction targets",
                "url": "https://example.com/article",
                "published_at": "2026-02-01T14:30:00Z",
                "topic": "climate change",
                "article_hash": "abc123def4567890"
            }
        }

    def generate_hash(self) -> str: # Generate unique hash based on title and URL
        content = f"{self.title.lower().strip()}|{str(self.url)}"
        return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]
    
    def model_post_init(self, __context): # Automatically generate hash after initialization if not provided
        if not self.article_hash:
            self.article_hash = self.generate_hash()