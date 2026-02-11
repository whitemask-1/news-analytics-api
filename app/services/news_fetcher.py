import os
import httpx
from datetime import datetime
from typing import Optional
import structlog # type: ignore

from app.services.secrets_manager import get_secret_from_env

logger = structlog.get_logger() # Logger for this module

class NewsAPIError(Exception):
    """Custom exception for News API errors."""
    pass

class NewsFetcher: #Service to fetch news articles from external APIs, currently supporting NewsAPI.org
    def __init__(self):
        # Get API key from Secrets Manager (production) or env var (local dev)
        self.api_key = get_secret_from_env('NEWS_API_KEY_SECRET_ARN', 'NEWS_API_KEY')
        self.base_url = os.getenv('NEWS_API_BASE_URL', 'https://newsapi.org/v2')
        self.client = httpx.AsyncClient(timeout=10.0)

    async def fetch_articles(self, query: str, limit: int =10, language: str = "en") -> dict:
        # Fetch articles from NewsAPI.org based on query, limit, and language
        # Returns a list of raw article dicts from NewsAPI
        # Raises NewsAPIError if the API returns an error

        url = f"{self.base_url}/everything"
        params = {
            "q": query,
            "pageSize": min(limit, 100),  # NewsAPI max page size is 100
            "language": language,
            "sortBy": "publishedAt",
            "apiKey": self.api_key
        }

        logger.info("fetching_articles", query=query, limit=limit)

        try: 
            response = await self.client.get(url, params=params)
            response.raise_for_status()

            data = response.json()

            #NewsAPI returns {"status": "ok", "totalResults": int, "articles": [...] }
            if data.get("status") != "ok":
                error_msg = data.get("message", "Unknown error")
                logger.error("newsapi_error", message=error_msg)
                raise NewsAPIError(f"NewsAPI error: {data.get('message', 'Unknown error')}")
            
            articles = data.get("articles", [])
            logger.info("fetched_articles", count=len(articles), query=query)

            return data
            
        except httpx.HTTPStatusError as e:
            logger.error("http_status_error", error=str(e), url=url, status_code=e.response.status_code)
            raise NewsAPIError(f"HTTP {e.response.status_code} error: {str(e)}")
        
        except httpx.RequestError as e:
            logger.error("network_error", error=str(e), url=url)
            raise NewsAPIError(f"Network error: {str(e)}")
        
        except Exception as e:
            logger.error("unexpected_fetch_error", error=str(e), url=url)
            raise NewsAPIError(f"Unexpected error: {str(e)}")
        
    async def close(self):
        await self.client.aclose()
