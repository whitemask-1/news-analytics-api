from datetime import datetime
from typing import Optional
import structlog # type: ignore
from dateutil import parser

from app.models.article import Article

logger = structlog.get_logger()


class NormalizationError(Exception):
    """Custom exception for normalization errors."""
    pass


class ArticleNormalizer:
    """Service to convert external API responses to canonical Article schema."""
    
    def normalize_newsapi_article(self, raw: dict, topic: Optional[str] = None) -> Optional[Article]:
        """Convert a NewsAPI article to normalized Article schema."""
        try:
            # Extract source name
            source_obj = raw.get("source", {})
            source_name = source_obj.get("name") or source_obj.get("id") or "unknown"
            
            # Validate title
            title = raw.get("title", "").strip()
            if not title or title.lower() == "[removed]":
                logger.warning("invalid_title", title=title, url=raw.get("url"))
                return None
            
            # Validate URL exists
            url = raw.get("url")
            if not url:
                logger.warning("missing_url", title=title)
                return None
            
            # Parse published date
            published_str = raw.get("publishedAt")
            if not published_str:
                logger.warning("missing_published_date", title=title)
                return None
            
            try:
                published_at = parser.isoparse(published_str)
            except (ValueError, TypeError) as e:
                logger.warning("invalid_date_format", 
                             date=published_str, 
                             title=title,
                             error=str(e))
                return None
            
            # Handle description (might be "[Removed]" or empty)
            description = raw.get("description", "").strip()
            if description.lower() == "[removed]" or not description:
                description = None
            
            # Create normalized article
            article = Article(
                source="newsapi",
                source_name=source_name,
                title=title,
                description=description,
                url=url,
                published_at=published_at,
                topic=topic
            )
            
            return article
            
        except Exception as e:
            logger.warning("normalization_failed", 
                         error=str(e), 
                         title=raw.get("title"),
                         error_type=type(e).__name__)
            return None
    
    def normalize_batch(
        self, 
        raw_articles: list[dict], 
        source: str = "newsapi", 
        topic: Optional[str] = None
    ) -> list[Article]:
        """Normalize a batch of articles, filtering out any that fail."""
        normalized = []
        failed_count = 0
        
        for raw in raw_articles:
            if source == "newsapi":
                article = self.normalize_newsapi_article(raw, topic)
                if article:
                    normalized.append(article)
                else:
                    failed_count += 1
            else:
                logger.warning("unsupported_source", source=source)
        
        success_rate = (len(normalized) / len(raw_articles) * 100) if raw_articles else 0
        
        logger.info("normalized_batch", 
                   input_count=len(raw_articles), 
                   output_count=len(normalized),
                   failed_count=failed_count,
                   success_rate=f"{success_rate:.1f}%",
                   source=source)
        
        return normalized
