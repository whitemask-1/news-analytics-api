"""
AWS Athena Service for News Analytics Queries

This module provides methods to query news articles stored in S3 using Athena.
Athena is a serverless SQL query engine - no infrastructure to manage, pay per query.

Pricing:
- $5 per TB of data scanned
- Partition pruning reduces scans by 90%+ (huge cost savings)
- Query result caching (24 hours) - repeated queries are free

Key Features:
- Execute SQL queries asynchronously
- Poll for completion with exponential backoff
- Return results as structured data
- Pre-built analytics queries (article counts, trending topics, distributions)

Cost Optimization Tips:
1. Always filter by partition keys (year, month, day, source)
2. Use LIMIT to reduce result size
3. SELECT only needed columns (Parquet is columnar)
4. Enable query result reuse in workgroup

Example Usage:
    >>> athena = AthenaService()
    >>> 
    >>> # Count articles by source
    >>> results = await athena.get_article_counts(
    >>>     start_date="2026-02-01",
    >>>     end_date="2026-02-06",
    >>>     group_by="source"
    >>> )
    >>> # Returns: [{"source": "newsapi", "count": 1250}, ...]
"""

import os
import time
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Any
import boto3
from botocore.exceptions import ClientError
import structlog

# Initialize structured logger
logger = structlog.get_logger(__name__)


class AthenaService:
    """
    AWS Athena query service for news analytics.
    
    Provides methods to execute SQL queries against articles stored in S3.
    Handles async query execution, result polling, and data parsing.
    
    Attributes:
        athena_client: Boto3 Athena client
        database_name: Glue database name
        workgroup: Athena workgroup for query execution
        output_location: S3 path for query results
    """
    
    def __init__(
        self,
        database_name: Optional[str] = None,
        workgroup: Optional[str] = None,
        output_location: Optional[str] = None,
        aws_region: Optional[str] = None
    ):
        """
        Initialize Athena service client.
        
        Args:
            database_name: Glue database name (defaults to env or "{project}_{env}")
            workgroup: Athena workgroup (defaults to env or "{project}-{env}")
            output_location: S3 path for results (defaults to env S3_BUCKET_ATHENA)
            aws_region: AWS region (defaults to env AWS_REGION_CUSTOM)
        """
        region = aws_region or os.getenv("AWS_REGION_CUSTOM", "us-east-1")
        self.athena_client = boto3.client("athena", region_name=region)
        
        # Get configuration from environment or use defaults
        project = os.getenv("PROJECT_NAME", "news-analytics")
        environment = os.getenv("ENVIRONMENT", "dev")
        
        self.database_name = database_name or os.getenv(
            "GLUE_DATABASE_NAME",
            f"{project}_{environment}"
        )
        
        self.workgroup = workgroup or os.getenv(
            "ATHENA_WORKGROUP",
            f"{project}-{environment}"
        )
        
        # S3 output location for query results
        athena_bucket = output_location or os.getenv("S3_BUCKET_ATHENA")
        if athena_bucket:
            self.output_location = f"s3://{athena_bucket}/query-results/"
        else:
            self.output_location = None  # Use workgroup default
        
        logger.info(
            "athena_service_initialized",
            database=self.database_name,
            workgroup=self.workgroup,
            region=region
        )
    
    async def execute_query(
        self,
        query: str,
        max_wait_seconds: int = 60,
        poll_interval: float = 1.0
    ) -> Dict[str, Any]:
        """
        Execute an Athena SQL query and wait for results.
        
        This method:
        1. Submits query to Athena (async execution)
        2. Polls for completion with exponential backoff
        3. Retrieves and parses results
        4. Returns structured data
        
        Args:
            query: SQL query string
            max_wait_seconds: Maximum time to wait for query completion
            poll_interval: Initial poll interval in seconds (doubles on each retry)
        
        Returns:
            Dictionary with query results:
            {
                "status": "success",
                "execution_id": "abc123...",
                "rows": [...],
                "columns": ["col1", "col2"],
                "row_count": 42,
                "data_scanned_bytes": 1234567,
                "execution_time_ms": 850
            }
        
        Raises:
            Exception: If query fails or times out
        
        Example:
            >>> query = "SELECT COUNT(*) as total FROM normalized_articles"
            >>> result = await athena.execute_query(query)
            >>> print(f"Total articles: {result['rows'][0]['total']}")
        """
        try:
            # Start query execution
            start_time = time.time()
            
            execution_params = {
                "QueryString": query,
                "QueryExecutionContext": {"Database": self.database_name},
                "WorkGroup": self.workgroup
            }
            
            # Add output location if specified (overrides workgroup default)
            if self.output_location:
                execution_params["ResultConfiguration"] = {
                    "OutputLocation": self.output_location
                }
            
            response = self.athena_client.start_query_execution(**execution_params)
            execution_id = response["QueryExecutionId"]
            
            logger.info(
                "query_started",
                execution_id=execution_id,
                query_preview=query[:100]
            )
            
            # Poll for completion with exponential backoff
            elapsed = 0
            current_interval = poll_interval
            
            while elapsed < max_wait_seconds:
                # Check query status
                execution_response = self.athena_client.get_query_execution(
                    QueryExecutionId=execution_id
                )
                
                status = execution_response["QueryExecution"]["Status"]["State"]
                
                if status == "SUCCEEDED":
                    # Query completed successfully
                    stats = execution_response["QueryExecution"]["Statistics"]
                    execution_time_ms = stats.get("EngineExecutionTimeInMillis", 0)
                    data_scanned_bytes = stats.get("DataScannedInBytes", 0)
                    
                    logger.info(
                        "query_succeeded",
                        execution_id=execution_id,
                        execution_time_ms=execution_time_ms,
                        data_scanned_mb=round(data_scanned_bytes / 1024 / 1024, 2),
                        data_scanned_cost_usd=round(data_scanned_bytes / 1024 / 1024 / 1024 / 1024 * 5, 4)
                    )
                    
                    # Fetch results
                    results = await self._fetch_results(execution_id)
                    
                    return {
                        "status": "success",
                        "execution_id": execution_id,
                        "rows": results["rows"],
                        "columns": results["columns"],
                        "row_count": len(results["rows"]),
                        "data_scanned_bytes": data_scanned_bytes,
                        "execution_time_ms": execution_time_ms
                    }
                
                elif status == "FAILED":
                    # Query failed
                    error_msg = execution_response["QueryExecution"]["Status"].get(
                        "StateChangeReason", "Unknown error"
                    )
                    logger.error(
                        "query_failed",
                        execution_id=execution_id,
                        error=error_msg
                    )
                    raise Exception(f"Query failed: {error_msg}")
                
                elif status == "CANCELLED":
                    logger.warning("query_cancelled", execution_id=execution_id)
                    raise Exception("Query was cancelled")
                
                # Still running, wait and retry
                await self._async_sleep(current_interval)
                elapsed += current_interval
                
                # Exponential backoff (1s -> 2s -> 4s -> 8s)
                current_interval = min(current_interval * 2, 10.0)
            
            # Timeout
            logger.error("query_timeout", execution_id=execution_id, elapsed=elapsed)
            raise Exception(f"Query timeout after {elapsed} seconds")
            
        except ClientError as e:
            logger.error("athena_client_error", error=str(e))
            raise
    
    async def _fetch_results(self, execution_id: str) -> Dict[str, Any]:
        """
        Fetch query results from Athena.
        
        Athena returns results paginated (1000 rows per page).
        This method handles pagination and parses results into structured data.
        
        Args:
            execution_id: Query execution ID
        
        Returns:
            Dictionary with columns and rows:
            {
                "columns": ["col1", "col2"],
                "rows": [{"col1": "val1", "col2": "val2"}, ...]
            }
        """
        try:
            # Get first page of results
            result_response = self.athena_client.get_query_results(
                QueryExecutionId=execution_id,
                MaxResults=1000
            )
            
            # Extract column names from metadata
            column_info = result_response["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]
            columns = [col["Name"] for col in column_info]
            
            # Extract rows
            rows = []
            result_rows = result_response["ResultSet"]["Rows"]
            
            # Skip first row if it contains column headers
            start_idx = 1 if len(result_rows) > 0 else 0
            
            for row in result_rows[start_idx:]:
                row_data = {}
                for i, col_name in enumerate(columns):
                    # Get cell value, handle missing data
                    data = row.get("Data", [])
                    if i < len(data):
                        row_data[col_name] = data[i].get("VarCharValue")
                    else:
                        row_data[col_name] = None
                rows.append(row_data)
            
            # Handle pagination if more results exist
            next_token = result_response.get("NextToken")
            while next_token:
                result_response = self.athena_client.get_query_results(
                    QueryExecutionId=execution_id,
                    NextToken=next_token,
                    MaxResults=1000
                )
                
                for row in result_response["ResultSet"]["Rows"]:
                    row_data = {}
                    for i, col_name in enumerate(columns):
                        data = row.get("Data", [])
                        if i < len(data):
                            row_data[col_name] = data[i].get("VarCharValue")
                        else:
                            row_data[col_name] = None
                    rows.append(row_data)
                
                next_token = result_response.get("NextToken")
            
            logger.debug(
                "results_fetched",
                execution_id=execution_id,
                row_count=len(rows),
                column_count=len(columns)
            )
            
            return {"columns": columns, "rows": rows}
            
        except ClientError as e:
            logger.error("fetch_results_error", execution_id=execution_id, error=str(e))
            raise
    
    async def _async_sleep(self, seconds: float):
        """Helper to sleep asynchronously (compatible with sync/async contexts)."""
        import asyncio
        try:
            await asyncio.sleep(seconds)
        except RuntimeError:
            # If no event loop, fall back to sync sleep
            time.sleep(seconds)
    
    # =========================================================================
    # ANALYTICS QUERIES
    # =========================================================================
    
    async def get_article_counts(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        group_by: str = "source"
    ) -> List[Dict[str, Any]]:
        """
        Get article counts grouped by specified field.
        
        Efficient query using partition pruning on date range.
        Only scans relevant partitions (huge cost savings).
        
        Args:
            start_date: Start date (YYYY-MM-DD, defaults to 7 days ago)
            end_date: End date (YYYY-MM-DD, defaults to today)
            group_by: Field to group by: "source", "source_name", "topic", or "day"
        
        Returns:
            List of count dictionaries:
            [
                {"source": "newsapi", "count": 1250},
                {"source": "guardian", "count": 85},
                ...
            ]
        
        Example:
            >>> # Get counts by source for last 7 days
            >>> counts = await athena.get_article_counts(group_by="source")
            >>> 
            >>> # Get daily counts for specific date range
            >>> counts = await athena.get_article_counts(
            >>>     start_date="2026-02-01",
            >>>     end_date="2026-02-06",
            >>>     group_by="day"
            >>> )
        """
        # Default to last 7 days if not specified
        if not end_date:
            end_date = date.today().isoformat()
        if not start_date:
            start_date = (date.today() - timedelta(days=7)).isoformat()
        
        # Validate group_by parameter
        valid_groups = ["source", "source_name", "topic", "day"]
        if group_by not in valid_groups:
            raise ValueError(f"group_by must be one of: {valid_groups}")
        
        # Build SELECT clause based on group_by
        if group_by == "day":
            select_clause = "DATE(published_at) as day"
            group_clause = "DATE(published_at)"
            order_clause = "day DESC"
        else:
            select_clause = group_by
            group_clause = group_by
            order_clause = "count DESC"
        
        # Build query with partition pruning
        query = f"""
            SELECT 
                {select_clause},
                COUNT(*) as count
            FROM normalized_articles
            WHERE published_at >= DATE '{start_date}'
              AND published_at <= DATE '{end_date}'
              {f"AND {group_by} IS NOT NULL" if group_by != "day" else ""}
            GROUP BY {group_clause}
            ORDER BY {order_clause};
        """
        
        logger.info(
            "executing_article_counts",
            start_date=start_date,
            end_date=end_date,
            group_by=group_by
        )
        
        result = await self.execute_query(query)
        
        # Convert count strings to integers
        for row in result["rows"]:
            if "count" in row:
                row["count"] = int(row["count"]) if row["count"] else 0
        
        return result["rows"]
    
    async def get_trending_topics(
        self,
        days: int = 7,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Get most common topics in the specified time period.
        
        Finds topics with most article coverage.
        Useful for identifying trending news subjects.
        
        Args:
            days: Number of days to look back (default: 7)
            limit: Maximum number of topics to return (default: 20)
        
        Returns:
            List of topic dictionaries sorted by frequency:
            [
                {
                    "topic": "artificial intelligence",
                    "count": 342,
                    "sources": 5
                },
                ...
            ]
        
        Example:
            >>> # Get top 10 trending topics in last 3 days
            >>> trending = await athena.get_trending_topics(days=3, limit=10)
            >>> for topic in trending:
            >>>     print(f"{topic['topic']}: {topic['count']} articles")
        """
        start_date = (date.today() - timedelta(days=days)).isoformat()
        
        query = f"""
            SELECT 
                topic,
                COUNT(*) as count,
                COUNT(DISTINCT source_name) as sources
            FROM normalized_articles
            WHERE published_at >= DATE '{start_date}'
              AND topic IS NOT NULL
              AND topic != ''
            GROUP BY topic
            ORDER BY count DESC
            LIMIT {limit};
        """
        
        logger.info(
            "executing_trending_topics",
            days=days,
            limit=limit
        )
        
        result = await self.execute_query(query)
        
        # Convert counts to integers
        for row in result["rows"]:
            if "count" in row:
                row["count"] = int(row["count"]) if row["count"] else 0
            if "sources" in row:
                row["sources"] = int(row["sources"]) if row["sources"] else 0
        
        return result["rows"]
    
    async def get_source_distribution(self) -> List[Dict[str, Any]]:
        """
        Get distribution of articles across sources and publishers.
        
        Shows which news sources provide the most content.
        Useful for understanding data source diversity.
        
        Returns:
            List of source statistics:
            [
                {
                    "source": "newsapi",
                    "publishers": 25,
                    "articles": 1250,
                    "oldest": "2026-02-01 10:30:00",
                    "newest": "2026-02-06 14:30:00"
                },
                ...
            ]
        
        Example:
            >>> distribution = await athena.get_source_distribution()
            >>> for src in distribution:
            >>>     print(f"{src['source']}: {src['articles']} articles from {src['publishers']} publishers")
        """
        query = """
            SELECT 
                source,
                COUNT(DISTINCT source_name) as publishers,
                COUNT(*) as articles,
                MIN(published_at) as oldest,
                MAX(published_at) as newest
            FROM normalized_articles
            GROUP BY source
            ORDER BY articles DESC;
        """
        
        logger.info("executing_source_distribution")
        
        result = await self.execute_query(query)
        
        # Convert counts to integers
        for row in result["rows"]:
            if "publishers" in row:
                row["publishers"] = int(row["publishers"]) if row["publishers"] else 0
            if "articles" in row:
                row["articles"] = int(row["articles"]) if row["articles"] else 0
        
        return result["rows"]


# =============================================================================
# MODULE-LEVEL SINGLETON
# =============================================================================

# Global instance for Lambda handlers to reuse across invocations
_athena_service: Optional[AthenaService] = None


def get_athena_service() -> AthenaService:
    """
    Get or create singleton Athena service instance.
    
    Lambda containers are reused, so maintain single service
    to reuse boto3 connections (efficiency).
    
    Returns:
        AthenaService instance (creates if doesn't exist)
    
    Example (in Lambda handler):
        >>> from app.services.athena import get_athena_service
        >>> 
        >>> async def handler(event, context):
        >>>     athena = get_athena_service()
        >>>     counts = await athena.get_article_counts()
    """
    global _athena_service
    
    if _athena_service is None:
        _athena_service = AthenaService()
        logger.info("athena_singleton_created")
    
    return _athena_service
