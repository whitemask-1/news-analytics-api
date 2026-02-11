"""
Redis Deduplication Service using Upstash REST API

This module provides article deduplication using Redis as a distributed hash cache.
Uses Upstash's HTTP REST API for serverless Redis access (no VPC configuration needed).

Key Features:
- Check if article hash exists before processing (prevents duplicate ingestion)
- Mark processed articles with TTL (14 days by default)
- Batch operations for efficient bulk checking
- Automatic expiration for memory efficiency

Memory Estimate:
- Each hash: ~16 bytes (SHA256 truncated to 16 chars)
- 100K articles: ~1.6 MB
- 500K articles (14 days @ ~35K/day): ~8 MB
- Upstash free tier: 10K commands/day (sufficient for 4 runs × 100 articles × 2 ops = 800/day)

Architecture Decision:
- Upstash REST API vs ElastiCache Redis
  ✓ Upstash: No VPC, simple HTTP calls, serverless pricing
  ✗ ElastiCache: Requires VPC Lambda (cold start penalty), fixed hourly cost
"""

import os
import json
from typing import List, Dict, Optional, Set, Any
from datetime import timedelta
import httpx
import structlog

from app.services.secrets_manager import get_secret_from_env

# Initialize structured logger
logger = structlog.get_logger(__name__)


class RedisDeduplication:
    """
    Redis-backed article deduplication service using Upstash REST API.
    
    This class provides methods to check and mark article hashes as processed,
    preventing duplicate article ingestion and wasting API quota/storage costs.
    
    Attributes:
        redis_url: Upstash Redis REST API endpoint URL
        redis_token: Authentication token for Upstash
        ttl_seconds: Time-to-live for article hashes (default: 14 days)
        client: Async HTTP client for REST API calls
    
    Example:
        >>> dedup = RedisDeduplication()
        >>> await dedup.connect()
        >>> 
        >>> # Check if article was already processed
        >>> is_dup = await dedup.check_article_exists("abc123hash")
        >>> if not is_dup:
        >>>     await process_article(article)
        >>>     await dedup.mark_article_processed("abc123hash")
    """
    
    def __init__(
        self,
        redis_url: Optional[str] = None,
        redis_token: Optional[str] = None,
        ttl_days: int = 14
    ):
        """
        Initialize Redis deduplication client.
        
        Args:
            redis_url: Upstash Redis REST API URL (defaults to Secrets Manager or env)
            redis_token: Upstash authentication token (defaults to Secrets Manager or env)
            ttl_days: Number of days to keep article hashes (default: 14)
                     After TTL expires, article can be re-ingested for updates
        
        Raises:
            ValueError: If redis_url or redis_token not provided and not in environment
        """
        # Get credentials from Secrets Manager (production) or env vars (local dev)
        # Allow None if not provided (caller should check before using)
        try:
            self.redis_url = redis_url or get_secret_from_env(
                'UPSTASH_REDIS_URL_SECRET_ARN', 
                'UPSTASH_REDIS_URL'
            )
            self.redis_token = redis_token or get_secret_from_env(
                'UPSTASH_REDIS_TOKEN_SECRET_ARN', 
                'UPSTASH_REDIS_TOKEN'
            )
        except ValueError as e:
            logger.warning(
                "redis_credentials_not_configured",
                error=str(e),
                message="Redis deduplication will not be available"
            )
            self.redis_url = None
            self.redis_token = None
        
        # Only raise error if explicitly trying to use Redis but credentials missing
        if not self.redis_url or not self.redis_token:
            logger.info(
                "redis_disabled",
                message="Redis credentials not found - deduplication will be skipped"
            )
        
        # Calculate TTL in seconds
        self.ttl_seconds = int(timedelta(days=ttl_days).total_seconds())
        
        # HTTP client for REST API calls (initialized in connect())
        self.client: Optional[httpx.AsyncClient] = None
        
        logger.info(
            "redis_client_initialized",
            ttl_days=ttl_days,
            ttl_seconds=self.ttl_seconds,
            redis_available=self.is_available()
        )
    
    def is_available(self) -> bool:
        """
        Check if Redis is configured and available for use.
        
        Returns:
            True if Redis credentials are configured, False otherwise
        """
        return bool(self.redis_url and self.redis_token)
    
    async def connect(self) -> None:
        """
        Initialize async HTTP client for Redis REST API.
        
        Call this before making any Redis operations.
        Safe to call multiple times (idempotent).
        """
        if self.client is None:
            if not self.redis_url or not self.redis_token:
                raise ValueError("Redis URL and token must be set before connecting")
            
            self.client = httpx.AsyncClient(
                base_url=self.redis_url,
                headers={
                    "Authorization": f"Bearer {self.redis_token}",
                    "Content-Type": "application/json"
                },
                timeout=5.0  # 5 second timeout for Redis operations
            )
            logger.info("redis_client_connected")
    
    async def close(self) -> None:
        """
        Close HTTP client connection.
        
        Call this when done with all Redis operations (e.g., Lambda shutdown).
        """
        if self.client:
            await self.client.aclose()
            self.client = None
            logger.info("redis_client_closed")
    
    async def _execute_command(self, command: List[str]) -> Any:
        """
        Execute a Redis command via Upstash REST API.
        
        Upstash REST API format:
        - POST to /pipeline endpoint with array of commands
        - Each command is array: ["COMMAND", "arg1", "arg2", ...]
        - Returns array of results
        
        Args:
            command: Redis command as list, e.g., ["GET", "key"]
        
        Returns:
            Command result (varies by command type)
        
        Raises:
            httpx.HTTPError: If REST API call fails
        """
        if not self.client:
            await self.connect()
        
        assert self.client is not None, "Client should be initialized after connect()"
        
        try:
            # Upstash REST API expects array of commands for pipeline
            response = await self.client.post("/pipeline", json=[command])
            response.raise_for_status()
            
            # Result is array with one element per command
            results = response.json()
            return results[0]["result"] if results else None
            
        except httpx.HTTPError as e:
            logger.error(
                "redis_command_failed",
                command=command[0],
                error=str(e)
            )
            raise
    
    async def check_article_exists(self, article_hash: str) -> bool:
        """
        Check if article hash exists in Redis (already processed).
        
        Uses Redis EXISTS command - O(1) time complexity.
        Returns immediately without blocking.
        
        Args:
            article_hash: SHA256 hash of article (typically 16 characters)
        
        Returns:
            True if hash exists (duplicate), False if new article
        
        Example:
            >>> exists = await dedup.check_article_exists("abc123def456")
            >>> if exists:
            >>>     logger.info("duplicate_article_skipped", hash=hash)
        """
        try:
            # EXISTS returns 1 if key exists, 0 if not
            result = await self._execute_command(["EXISTS", article_hash])
            exists = result == 1
            
            logger.debug(
                "article_existence_checked",
                article_hash=article_hash,
                exists=exists
            )
            
            return exists
            
        except Exception as e:
            logger.error(
                "check_exists_error",
                article_hash=article_hash,
                error=str(e)
            )
            # On error, assume not exists to avoid blocking ingestion
            # Trade-off: May ingest duplicate if Redis is down
            return False
    
    async def batch_check_exists(self, article_hashes: List[str]) -> List[bool]:
        """
        Check multiple article hashes in a single batch operation.
        
        More efficient than calling check_article_exists() in a loop.
        Uses Redis pipeline to send all EXISTS commands at once.
        
        Args:
            article_hashes: List of article hashes to check
        
        Returns:
            List of booleans (same order as input):
            - True = hash exists (duplicate)
            - False = hash is new
        
        Example:
            >>> hashes = ["hash1", "hash2", "hash3"]
            >>> results = await dedup.batch_check_exists(hashes)
            >>> # results = [True, False, True]
            >>> new_hashes = [h for h, is_dup in zip(hashes, results) if not is_dup]
            >>> # new_hashes = ["hash2"]
        """
        if not article_hashes:
            return []
        
        try:
            # Build pipeline of EXISTS commands
            commands = [["EXISTS", hash_val] for hash_val in article_hashes]
            
            # Execute all commands in one request
            if not self.client:
                await self.connect()
            
            assert self.client is not None, "Client should be initialized after connect()"
            
            response = await self.client.post("/pipeline", json=commands)
            response.raise_for_status()
            results = response.json()
            
            # Convert Redis results (1/0) to boolean
            exists_list = [item["result"] == 1 for item in results]
            
            # Calculate statistics
            total = len(exists_list)
            duplicates = sum(exists_list)
            new = total - duplicates
            
            logger.info(
                "batch_existence_checked",
                total_checked=total,
                duplicates_found=duplicates,
                new_articles=new,
                duplicate_percentage=round(duplicates / total * 100, 1) if total > 0 else 0
            )
            
            return exists_list
            
        except Exception as e:
            logger.error(
                "batch_check_error",
                hash_count=len(article_hashes),
                error=str(e)
            )
            # On error, assume all are new to avoid blocking ingestion
            return [False] * len(article_hashes)
    
    async def mark_article_processed(self, article_hash: str) -> bool:
        """
        Mark article as processed by storing hash in Redis with TTL.
        
        Uses Redis SETEX command to set key with automatic expiration.
        After TTL expires (14 days), hash is automatically deleted.
        Value is set to "1" (we only care about key existence).
        
        Args:
            article_hash: SHA256 hash to mark as processed
        
        Returns:
            True if successfully marked, False on error
        
        Example:
            >>> await dedup.mark_article_processed("abc123def456")
            >>> # Hash is stored for 14 days, then auto-deleted
        """
        try:
            # SETEX key seconds value
            # Sets key with expiration in one atomic operation
            result = await self._execute_command([
                "SETEX",
                article_hash,
                str(self.ttl_seconds),
                "1"  # Value doesn't matter, we only check existence
            ])
            
            logger.debug(
                "article_marked_processed",
                article_hash=article_hash,
                ttl_seconds=self.ttl_seconds
            )
            
            return result == "OK"
            
        except Exception as e:
            logger.error(
                "mark_processed_error",
                article_hash=article_hash,
                error=str(e)
            )
            # Don't raise - marking failure shouldn't block the pipeline
            return False
    
    async def batch_mark_processed(self, article_hashes: List[str]) -> int:
        """
        Mark multiple articles as processed in a single batch operation.
        
        More efficient than calling mark_article_processed() in a loop.
        Uses Redis pipeline to execute all SETEX commands at once.
        
        Args:
            article_hashes: List of hashes to mark as processed
        
        Returns:
            Number of hashes successfully marked
        
        Example:
            >>> hashes = ["hash1", "hash2", "hash3"]
            >>> marked_count = await dedup.batch_mark_processed(hashes)
            >>> logger.info("marked_articles", count=marked_count)
        """
        if not article_hashes:
            return 0
        
        try:
            # Build pipeline of SETEX commands
            commands = [
                ["SETEX", hash_val, str(self.ttl_seconds), "1"]
                for hash_val in article_hashes
            ]
            
            # Execute all commands in one request
            if not self.client:
                await self.connect()
            
            assert self.client is not None, "Client should be initialized after connect()"
            
            response = await self.client.post("/pipeline", json=commands)
            response.raise_for_status()
            results = response.json()
            
            # Count successful operations (result == "OK")
            success_count = sum(1 for item in results if item["result"] == "OK")
            
            logger.info(
                "batch_marked_processed",
                total_hashes=len(article_hashes),
                successful=success_count,
                failed=len(article_hashes) - success_count
            )
            
            return success_count
            
        except Exception as e:
            logger.error(
                "batch_mark_error",
                hash_count=len(article_hashes),
                error=str(e)
            )
            return 0
    
    async def get_stats(self) -> Dict[str, Any]:
        """
        Get Redis statistics for monitoring.
        
        Returns:
            Dictionary with Redis stats:
            - total_keys: Total number of article hashes stored
            - memory_used_mb: Approximate memory usage
            - uptime_seconds: Redis instance uptime (if available)
        
        Example:
            >>> stats = await dedup.get_stats()
            >>> logger.info("redis_stats", **stats)
        """
        try:
            # Get count of keys matching our pattern
            # DBSIZE returns total keys in database
            total_keys = await self._execute_command(["DBSIZE"])
            
            # Estimate memory: 16 bytes per hash + overhead
            estimated_memory_mb = (total_keys * 50) / (1024 * 1024)  # 50 bytes per key with overhead
            
            return {
                "total_keys": total_keys,
                "memory_used_mb": round(estimated_memory_mb, 2),
                "ttl_days": self.ttl_seconds / 86400
            }
            
        except Exception as e:
            logger.error("get_stats_error", error=str(e))
            return {"error": str(e)}


# =============================================================================
# MODULE-LEVEL SINGLETON
# =============================================================================

# Global instance for Lambda handlers to reuse across invocations
# Lambda container reuse allows connection pooling between invocations
_redis_client: Optional[RedisDeduplication] = None


def get_redis_client() -> RedisDeduplication:
    """
    Get or create singleton Redis client instance.
    
    Lambda containers are reused across invocations, so we maintain
    a single client instance to reuse HTTP connections (efficiency).
    
    Returns:
        RedisDeduplication instance (creates if doesn't exist)
    
    Example (in Lambda handler):
        >>> from app.services.redis_client import get_redis_client
        >>> 
        >>> async def handler(event, context):
        >>>     redis = get_redis_client()
        >>>     await redis.connect()  # No-op if already connected
        >>>     exists = await redis.check_article_exists(hash)
    """
    global _redis_client
    
    if _redis_client is None:
        ttl_days = int(os.getenv("REDIS_TTL_DAYS", "14"))
        _redis_client = RedisDeduplication(ttl_days=ttl_days)
        logger.info("redis_singleton_created", ttl_days=ttl_days)
    
    return _redis_client
