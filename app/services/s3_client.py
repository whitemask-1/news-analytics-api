"""
S3 Storage Service for News Analytics

This module handles all S3 operations for storing news articles in two formats:
1. Raw articles: JSON format (original NewsAPI response)
2. Normalized articles: Parquet format (optimized for Athena queries)

Storage Architecture:
- Raw bucket: Stores original API responses for debugging and reprocessing
  Path: raw/YYYY/MM/DD/HH/{query}_{timestamp}.json
  Lifecycle: Delete after 7 days (saves costs)

- Normalized bucket: Stores processed articles in Parquet format
  Path: normalized/year=YYYY/month=MM/day=DD/source={source}/articles.parquet
  Lifecycle: Keep indefinitely for analytics
  Partitioning: By date and source for efficient Athena queries

Cost Optimization:
- Parquet format: 2-3x smaller than JSON, faster Athena scans (less data = less cost)
- Partitioning: Athena only scans relevant partitions (90%+ cost reduction)
- Lifecycle policies: Auto-delete raw after 7 days

Example Usage:
    >>> s3 = S3Client(
    >>>     raw_bucket="news-raw",
    >>>     normalized_bucket="news-normalized"
    >>> )
    >>> 
    >>> # Store raw API response
    >>> await s3.store_raw_articles(articles, query="AI", timestamp=datetime.now())
    >>> 
    >>> # Store normalized articles in Parquet
    >>> await s3.store_normalized_articles(normalized_articles)
"""

import os
import json
import io
from datetime import datetime
from typing import List, Dict, Optional, Any
from pathlib import Path
import boto3
from botocore.exceptions import ClientError
import structlog
import pyarrow as pa
import pyarrow.parquet as pq

# Initialize structured logger
logger = structlog.get_logger(__name__)


class S3Client:
    """
    S3 storage client for news articles.
    
    Handles storing articles in two formats:
    - Raw: Original JSON from NewsAPI (for debugging/reprocessing)
    - Normalized: Parquet format (for efficient Athena analytics)
    
    Attributes:
        raw_bucket: S3 bucket name for raw articles
        normalized_bucket: S3 bucket name for normalized articles
        athena_results_bucket: S3 bucket for Athena query results
        s3_client: Boto3 S3 client instance
    """
    
    def __init__(
        self,
        raw_bucket: Optional[str] = None,
        normalized_bucket: Optional[str] = None,
        athena_results_bucket: Optional[str] = None,
        aws_region: Optional[str] = None
    ):
        """
        Initialize S3 client with bucket names.
        
        Args:
            raw_bucket: Bucket for raw JSON articles (defaults to env S3_BUCKET_RAW)
            normalized_bucket: Bucket for normalized Parquet (defaults to env S3_BUCKET_NORMALIZED)
            athena_results_bucket: Bucket for Athena results (defaults to env S3_BUCKET_ATHENA)
            aws_region: AWS region (defaults to env AWS_REGION_CUSTOM)
        
        Raises:
            ValueError: If required bucket names not provided
        """
        self.raw_bucket = raw_bucket or os.getenv("S3_BUCKET_RAW")
        self.normalized_bucket = normalized_bucket or os.getenv("S3_BUCKET_NORMALIZED")
        self.athena_results_bucket = athena_results_bucket or os.getenv("S3_BUCKET_ATHENA")
        
        if not self.raw_bucket or not self.normalized_bucket:
            raise ValueError(
                "S3 bucket names required. Set S3_BUCKET_RAW and S3_BUCKET_NORMALIZED "
                "environment variables or pass to constructor."
            )
        
        # Initialize boto3 S3 client
        region = aws_region or os.getenv("AWS_REGION_CUSTOM", "us-east-1")
        self.s3_client = boto3.client("s3", region_name=region)
        
        logger.info(
            "s3_client_initialized",
            raw_bucket=self.raw_bucket,
            normalized_bucket=self.normalized_bucket,
            region=region
        )
    
    def _generate_raw_key(self, query: str, timestamp: datetime) -> str:
        """
        Generate S3 key for raw article storage.
        
        Path structure: raw/YYYY/MM/DD/HH/{query}_{timestamp}.json
        Example: raw/2026/02/06/14/ai_20260206_143052.json
        
        This structure allows:
        - Easy browsing by date/time in S3 console
        - Lifecycle rules by prefix (e.g., delete raw/2026/01/*)
        - Debugging specific ingestion runs
        
        Args:
            query: Search query used (sanitized for S3 key)
            timestamp: When articles were fetched
        
        Returns:
            S3 key path string
        """
        # Sanitize query for S3 key (replace spaces/special chars with underscore)
        safe_query = "".join(c if c.isalnum() else "_" for c in query.lower())
        safe_query = safe_query[:50]  # Limit length
        
        # Generate hierarchical path
        key = (
            f"raw/"
            f"{timestamp.year:04d}/"
            f"{timestamp.month:02d}/"
            f"{timestamp.day:02d}/"
            f"{timestamp.hour:02d}/"
            f"{safe_query}_{timestamp.strftime('%Y%m%d_%H%M%S')}.json"
        )
        
        return key
    
    def _generate_normalized_key(self, source: str, timestamp: datetime) -> str:
        """
        Generate S3 key for normalized article storage (Parquet format).
        
        Path structure: normalized/year=YYYY/month=MM/day=DD/source={source}/articles.parquet
        Example: normalized/year=2026/month=02/day=06/source=newsapi/articles_143052.parquet
        
        Hive-style partitioning (key=value) enables:
        - Athena partition projection (automatic partition discovery)
        - Efficient query filtering (WHERE year=2026 AND month=2 AND source='newsapi')
        - 90%+ cost reduction by scanning only relevant partitions
        
        Args:
            source: Article source (e.g., "newsapi", "guardian")
            timestamp: When articles were processed
        
        Returns:
            S3 key path string with Hive partitioning
        """
        # Sanitize source name
        safe_source = "".join(c if c.isalnum() else "_" for c in source.lower())
        
        # Generate Hive-partitioned path
        key = (
            f"normalized/"
            f"year={timestamp.year:04d}/"
            f"month={timestamp.month:02d}/"
            f"day={timestamp.day:02d}/"
            f"source={safe_source}/"
            f"articles_{timestamp.strftime('%H%M%S')}.parquet"
        )
        
        return key
    
    async def store_raw_articles(
        self,
        articles: List[Dict[str, Any]],
        query: str,
        timestamp: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Store raw articles in JSON format for debugging and reprocessing.
        
        Stores the original NewsAPI response without modification.
        Useful for:
        - Debugging normalization issues
        - Reprocessing articles with updated logic
        - Audit trail of what was fetched
        
        Args:
            articles: List of raw article dictionaries from NewsAPI
            query: Search query used to fetch these articles
            timestamp: When articles were fetched (defaults to now)
        
        Returns:
            Dictionary with storage result:
            {
                "status": "success",
                "key": "raw/2026/02/06/14/ai_20260206_143052.json",
                "bucket": "news-raw-articles",
                "size_bytes": 45678,
                "article_count": 100
            }
        
        Raises:
            ClientError: If S3 upload fails
        
        Example:
            >>> result = await s3.store_raw_articles(
            >>>     articles=response["articles"],
            >>>     query="artificial intelligence",
            >>>     timestamp=datetime.now()
            >>> )
            >>> logger.info("raw_stored", **result)
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        try:
            # Generate S3 key with hierarchical structure
            key = self._generate_raw_key(query, timestamp)
            
            # Prepare JSON payload
            payload = {
                "query": query,
                "fetched_at": timestamp.isoformat(),
                "article_count": len(articles),
                "articles": articles
            }
            
            # Convert to JSON bytes
            json_bytes = json.dumps(payload, indent=2, default=str).encode("utf-8")
            
            # Upload to S3
            self.s3_client.put_object(
                Bucket=self.raw_bucket,
                Key=key,
                Body=json_bytes,
                ContentType="application/json",
                Metadata={
                    "query": query,
                    "article_count": str(len(articles)),
                    "fetched_at": timestamp.isoformat()
                }
            )
            
            result = {
                "status": "success",
                "key": key,
                "bucket": self.raw_bucket,
                "size_bytes": len(json_bytes),
                "article_count": len(articles)
            }
            
            logger.info(
                "raw_articles_stored",
                **result,
                query=query
            )
            
            return result
            
        except ClientError as e:
            logger.error(
                "raw_storage_failed",
                error=str(e),
                query=query,
                article_count=len(articles)
            )
            raise
    
    async def store_normalized_articles(
        self,
        articles: List[Dict[str, Any]],
        timestamp: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Store normalized articles in Parquet format for Athena analytics.
        
        Parquet benefits:
        - Columnar format: 2-3x smaller than JSON
        - Schema validation: Ensures data quality
        - Fast scans: Athena reads only needed columns
        - Compression: Built-in snappy compression
        
        Partitioning strategy:
        - By date (year/month/day): Query specific time ranges efficiently
        - By source: Filter by news provider
        - Partition projection: Athena auto-discovers partitions (no MSCK REPAIR)
        
        Args:
            articles: List of normalized article dictionaries
                     Each must have: source, title, url, published_at, article_hash
            timestamp: Processing timestamp (defaults to now)
        
        Returns:
            Dictionary with storage results per source:
            {
                "status": "success",
                "files_written": 2,
                "total_articles": 100,
                "sources": {
                    "newsapi": {"key": "...", "count": 85, "size_bytes": 12345},
                    "guardian": {"key": "...", "count": 15, "size_bytes": 2345}
                }
            }
        
        Example:
            >>> normalized = [
            >>>     {"source": "newsapi", "title": "...", "url": "...", ...},
            >>>     {"source": "newsapi", "title": "...", "url": "...", ...}
            >>> ]
            >>> result = await s3.store_normalized_articles(normalized)
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        if not articles:
            logger.warning("no_articles_to_store")
            return {"status": "success", "files_written": 0, "total_articles": 0}
        
        try:
            # Group articles by source for separate files
            # Athena performs better with fewer large files vs many small files
            articles_by_source: Dict[str, List[Dict]] = {}
            for article in articles:
                source = article.get("source", "unknown")
                if source not in articles_by_source:
                    articles_by_source[source] = []
                articles_by_source[source].append(article)
            
            results = {}
            total_size = 0
            
            # Write one Parquet file per source
            for source, source_articles in articles_by_source.items():
                # Convert to PyArrow Table (validates schema)
                table = self._articles_to_parquet_table(source_articles)
                
                # Generate S3 key with Hive partitioning
                key = self._generate_normalized_key(source, timestamp)
                
                # Write Parquet to bytes buffer
                parquet_buffer = io.BytesIO()
                pq.write_table(
                    table,
                    parquet_buffer,
                    compression="snappy",  # Good balance of speed vs compression
                    use_dictionary=True,    # Dictionary encoding for repeated values
                    write_statistics=True   # Enable Parquet statistics for query optimization
                )
                
                parquet_bytes = parquet_buffer.getvalue()
                
                # Upload to S3
                self.s3_client.put_object(
                    Bucket=self.normalized_bucket,
                    Key=key,
                    Body=parquet_bytes,
                    ContentType="application/x-parquet",
                    Metadata={
                        "source": source,
                        "article_count": str(len(source_articles)),
                        "processed_at": timestamp.isoformat()
                    }
                )
                
                results[source] = {
                    "key": key,
                    "count": len(source_articles),
                    "size_bytes": len(parquet_bytes)
                }
                total_size += len(parquet_bytes)
                
                logger.info(
                    "normalized_articles_stored",
                    source=source,
                    key=key,
                    article_count=len(source_articles),
                    size_bytes=len(parquet_bytes)
                )
            
            final_result = {
                "status": "success",
                "files_written": len(results),
                "total_articles": len(articles),
                "total_size_bytes": total_size,
                "sources": results
            }
            
            logger.info("all_normalized_articles_stored", **final_result)
            
            return final_result
            
        except Exception as e:
            logger.error(
                "normalized_storage_failed",
                error=str(e),
                article_count=len(articles)
            )
            raise
    
    def _articles_to_parquet_table(self, articles: List[Dict[str, Any]]) -> pa.Table:
        """
        Convert article dictionaries to PyArrow Table for Parquet writing.
        
        Defines explicit schema for data validation and type safety.
        Athena reads this schema to understand column types.
        
        Args:
            articles: List of normalized article dictionaries
        
        Returns:
            PyArrow Table with defined schema
        """
        # Define Parquet schema (matches Athena table schema)
        schema = pa.schema([
            ("source", pa.string()),           # API source: newsapi, guardian, etc.
            ("source_name", pa.string()),      # Publisher: bbc, cnn, etc.
            ("title", pa.string()),            # Article title
            ("description", pa.string()),      # Article description (nullable)
            ("url", pa.string()),              # Article URL
            ("published_at", pa.timestamp("us")),  # Publication timestamp (microseconds)
            ("topic", pa.string()),            # Search topic/query (nullable)
            ("article_hash", pa.string()),     # Deduplication hash
            ("ingested_at", pa.timestamp("us"))  # When we ingested (for tracking)
        ])
        
        # Extract columns from article dicts
        # Handle missing/null values gracefully
        current_time = datetime.utcnow()
        
        data = {
            "source": [a.get("source", "unknown") for a in articles],
            "source_name": [a.get("source_name", "") for a in articles],
            "title": [a.get("title", "") for a in articles],
            "description": [a.get("description") for a in articles],  # Can be None
            "url": [a.get("url", "") for a in articles],
            "published_at": [
                datetime.fromisoformat(a["published_at"].replace("Z", "+00:00"))
                if isinstance(a.get("published_at"), str)
                else a.get("published_at", current_time)
                for a in articles
            ],
            "topic": [a.get("topic") for a in articles],  # Can be None
            "article_hash": [a.get("article_hash", "") for a in articles],
            "ingested_at": [current_time for _ in articles]
        }
        
        # Create PyArrow Table from dict
        table = pa.table(data, schema=schema)
        
        return table
    
    async def list_raw_files(
        self,
        prefix: Optional[str] = None,
        max_keys: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List raw article files in S3.
        
        Useful for debugging and monitoring ingestion history.
        
        Args:
            prefix: S3 key prefix to filter (e.g., "raw/2026/02/06/")
            max_keys: Maximum number of files to return
        
        Returns:
            List of file metadata dictionaries
        """
        try:
            prefix = prefix or "raw/"
            
            response = self.s3_client.list_objects_v2(
                Bucket=self.raw_bucket,
                Prefix=prefix,
                MaxKeys=max_keys
            )
            
            files = []
            for obj in response.get("Contents", []):
                files.append({
                    "key": obj["Key"],
                    "size_bytes": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat()
                })
            
            logger.info(
                "raw_files_listed",
                prefix=prefix,
                file_count=len(files)
            )
            
            return files
            
        except ClientError as e:
            logger.error("list_raw_files_failed", error=str(e), prefix=prefix)
            return []


# =============================================================================
# MODULE-LEVEL SINGLETON
# =============================================================================

# Global instance for Lambda handlers to reuse across invocations
_s3_client: Optional[S3Client] = None


def get_s3_client() -> S3Client:
    """
    Get or create singleton S3 client instance.
    
    Lambda containers are reused, so maintain single client
    to reuse boto3 connections (efficiency).
    
    Returns:
        S3Client instance (creates if doesn't exist)
    
    Example (in Lambda handler):
        >>> from app.services.s3_client import get_s3_client
        >>> 
        >>> async def handler(event, context):
        >>>     s3 = get_s3_client()
        >>>     await s3.store_normalized_articles(articles)
    """
    global _s3_client
    
    if _s3_client is None:
        _s3_client = S3Client()
        logger.info("s3_singleton_created")
    
    return _s3_client
