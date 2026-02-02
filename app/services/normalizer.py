from datetime import datetime
from typing import Optional
import structlog
from dateutil import parser

from app.models.article import Article # Pydantic model for normalized article

logger = structlog.get_logger() # Logger for this module

class NormalizationError(Exception):
    """Custom exception for normalization errors."""
    pass

class ArticleNormalizer: # Service to convert external API responses to canonical Article schema

    def normalize_newsapi_article(self, raw: dict, topic: Optional[str] = None) -> Optional[Article]:
        """
        Convert a NewsAPI article to normalized Article schema.
        
        NewsAPI format:
        {
            "source": {"id": "...", "name": "CNN"},
            "author": "...",
            "title": "...",
            "description": "...",
            "url": "...",
            "publishedAt": "2026-02-01T14:30:00Z"
        }
        
        Returns None if article is invalid or cannot be normalized.
        """
        try:
            #Extract source name
            source_obj = raw.get("source", {})
            source_name = source_obj.get("name") or source_obj.get("id") or "unknown"

            #Parse published date
            published_str = raw.get("publishedAt")
            if not published_str:
                logger.warning("missing_published_date", article=raw.get("title"))
                return None
            
            published_at = parser.isoparse(published_str)

            #Create normalized article
            article = Article (
                source=source_name.lower().replace(" ", ""),
                title=raw.get("title", "").strip(),
                description=raw.get("description", "").strip() or None,
                url=raw["url"], #Will raise KeyError if missing
                published_at=published_at,
                topic=topic
            )

            return article
        
        except Exception as e:
            logger.warning("normalization_failed", error=str(e), article=raw.get("title"))
            return None
        
    def normalize_batch(self, raw_articles: list[dict], source: str = "newsapi", topic: Optional[str] = None) -> list[Article]:
        """
        Normalize a batch of articles, filtering out any that fail.
        
        Args:
            raw_articles: List of raw article dicts from external API
            source: Which API they came from (for routing to correct normalizer)
            topic: The search query used to find these articles
            
        Returns:
            List of successfully normalized Article objects
        """
        normalized = []

        for raw in raw_articles:
            if source == "newsapi":
                article = self.normalize_newsapi_article(raw, topic)
                if article:
                    normalized.append(article)
            else:
                logger.warning("unsupported_source", source=source)
        
        logger.info("normalized_batch", input_count=len(raw_articles), output_count=len(normalized), success_rate=f"{len(normalized)/len(raw_articles)*100:.1f}%",source=source)
        
        return normalized
