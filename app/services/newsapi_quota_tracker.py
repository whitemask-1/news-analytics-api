import structlog
from datetime import datetime, timedelta
from typing import Optional

logger = structlog.get_logger()


class NewsAPIQuotaTracker:
    """
    Track external API quota usage.
    
    In production, this would use Redis or a database.
    For now, uses in-memory storage (resets on restart).
    """
    
    def __init__(self, daily_limit: int = 100):
        self.daily_limit = daily_limit
        self.requests_today = 0
        self.reset_date = datetime.now().date()
    
    def check_and_increment(self) -> bool:
        """
        Check if quota is available and increment counter.
        
        Returns:
            True if request is allowed, False if quota exceeded
        """
        # Reset counter if it's a new day
        today = datetime.now().date()
        if today > self.reset_date:
            self.requests_today = 0
            self.reset_date = today
            logger.info("quota_reset", date=str(today))
        
        # Check quota
        if self.requests_today >= self.daily_limit:
            logger.warning("quota_exceeded", requests_today=self.requests_today, daily_limit=self.daily_limit)
            return False
        
        # Increment and allow
        self.requests_today += 1
        logger.info("quota_check", requests_today=self.requests_today, remaining=self.daily_limit - self.requests_today)
        return True
    
    def get_remaining(self) -> int:
        """Get remaining quota for today"""
        return max(0, self.daily_limit - self.requests_today)


# Global instance of NewsAPIQuotaTracker with a daily limit of 100 requests
newsapi_quota_tracker = NewsAPIQuotaTracker(daily_limit=100)