"""
Lambda Worker Handler for Article Processing

This handler processes article ingestion requests from SQS.
Runs the full ingestion pipeline with Redis deduplication.

Processing Pipeline:
1. Parse SQS message (query, limit, language)
2. Fetch articles from NewsAPI
3. Calculate article hashes
4. Batch-check Redis for existing hashes (deduplication)
5. Filter out duplicates
6. Normalize only new articles
7. Store raw + normalized to S3
8. Mark new hashes as processed in Redis
9. Return success metrics

Deduplication Flow:
- Redis stores article hashes with 14-day TTL
- Before processing, check if hash exists
- Skip articles already in Redis (prevents duplicate storage)
- After processing, mark new hashes (prevents future duplicates)

Benefits:
- Saves NewsAPI quota (don't re-fetch same articles)
- Saves S3 costs (don't re-store duplicates)
- Maintains data quality (no duplicate analytics)

Memory Efficiency:
- Only stores hashes in Redis (~16 bytes each)
- 14-day TTL = ~500K articles = ~8 MB
- Automatic cleanup via TTL expiration
"""

import json
import os
from datetime import datetime
from typing import Dict, Any, List
import structlog

from app.services.news_fetcher import NewsFetcher
from app.services.normalizer import ArticleNormalizer
from app.services.redis_client import get_redis_client
from app.services.s3_client import get_s3_client

# Initialize structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


async def process_single_message(message_body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a single SQS message (article ingestion request).
    
    This function runs the complete ingestion pipeline:
    - Fetch articles from NewsAPI
    - Check Redis for duplicates (deduplication)
    - Normalize only new articles
    - Store to S3 (raw + normalized)
    - Mark new hashes in Redis
    
    Args:
        message_body: Parsed SQS message with query/limit/language
    
    Returns:
        Processing result dictionary with metrics:
        {
            "status": "success",
            "query": "AI",
            "fetched": 100,
            "duplicates": 35,
            "new_articles": 65,
            "stored": 65,
            "processing_time_ms": 8500
        }
    
    Raises:
        Exception: If any step fails (message will retry or go to DLQ)
    """
    start_time = datetime.now()
    
    # Extract parameters from message
    query = message_body.get("query", "")
    limit = message_body.get("limit", 100)
    language = message_body.get("language", "en")
    source = message_body.get("source", "unknown")
    
    logger.info(
        "processing_ingestion_request",
        query=query,
        limit=limit,
        language=language,
        source=source
    )
    
    # Initialize Redis (optional for local development)
    redis = None
    use_redis = os.getenv("UPSTASH_REDIS_URL") and os.getenv("UPSTASH_REDIS_TOKEN")
    
    if use_redis:
        redis = get_redis_client()
        await redis.connect()
        logger.info("redis_enabled", message="Deduplication active")
    else:
        logger.warning(
            "redis_disabled",
            message="Running without Redis - deduplication disabled. All articles will be processed."
        )
    
    # Initialize S3 (optional for local development)
    s3 = None
    use_s3 = os.getenv("S3_BUCKET_RAW") and os.getenv("S3_BUCKET_NORMALIZED")
    
    if use_s3:
        s3 = get_s3_client()
        logger.info("s3_enabled", message="Article storage active")
    else:
        logger.warning(
            "s3_disabled",
            message="Running without S3 - articles will be logged but not stored."
        )
    
    news_fetcher = NewsFetcher()
    normalizer = ArticleNormalizer()
    
    try:
        # Step 1: Fetch articles from NewsAPI
        logger.info("fetching_articles", query=query, limit=limit)
        
        raw_response = await news_fetcher.fetch_articles(
            query=query,
            limit=limit,
            language=language
        )
        
        raw_articles = raw_response.get("articles", [])
        total_fetched = len(raw_articles)
        
        logger.info(
            "articles_fetched",
            query=query,
            count=total_fetched
        )
        
        if total_fetched == 0:
            logger.warning("no_articles_fetched", query=query)
            return {
                "status": "success",
                "query": query,
                "fetched": 0,
                "duplicates": 0,
                "new_articles": 0,
                "stored": 0,
                "message": "No articles found for query"
            }
        
        # Step 2: Calculate article hashes early (for deduplication)
        # Hash format: SHA256(url + title) truncated to 16 chars
        logger.info("calculating_article_hashes", count=total_fetched)
        
        article_hashes = []
        for article in raw_articles:
            # Use same hash calculation as normalizer for consistency
            import hashlib
            title = article.get("title", "")
            url = article.get("url", "")
            hash_input = f"{title.lower().strip()}|{str(url)}"
            article_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]
            article_hashes.append(article_hash)
        
        # Step 3: Batch-check Redis for existing hashes (deduplication)
        new_articles = []
        new_hashes = []
        duplicate_count = 0
        
        if redis:
            logger.info("checking_redis_for_duplicates", hash_count=len(article_hashes))
            
            exists_list = await redis.batch_check_exists(article_hashes)
            
            # Step 4: Filter out duplicate articles
            # exists_list[i] = True means article[i] already processed
            for i, (article, hash_val, exists) in enumerate(zip(raw_articles, article_hashes, exists_list)):
                if exists:
                    # Duplicate - skip this article
                    duplicate_count += 1
                    logger.debug(
                        "duplicate_article_skipped",
                        hash=hash_val,
                        title=article.get("title", "")[:50]
                    )
                else:
                    # New article - keep for processing
                    new_articles.append(article)
                    new_hashes.append(hash_val)
        else:
            # No Redis - process all articles (no deduplication)
            logger.info("deduplication_skipped", message="Redis not configured, processing all articles")
            new_articles = raw_articles
            new_hashes = article_hashes
        
        new_count = len(new_articles)
        duplicate_percentage = round(duplicate_count / total_fetched * 100, 1) if total_fetched > 0 else 0
        
        logger.info(
            "deduplication_complete",
            total_fetched=total_fetched,
            duplicates=duplicate_count,
            new_articles=new_count,
            duplicate_percentage=duplicate_percentage
        )
        
        if new_count == 0:
            logger.info("all_articles_duplicates", query=query)
            return {
                "status": "success",
                "query": query,
                "fetched": total_fetched,
                "duplicates": duplicate_count,
                "new_articles": 0,
                "stored": 0,
                "message": "All articles were duplicates (already processed)"
            }
        
        # Step 5: Normalize only new articles
        logger.info("normalizing_new_articles", count=new_count)
        
        normalized_models = normalizer.normalize_batch(new_articles, topic=query)
        normalized_articles = [a.model_dump() for a in normalized_models]
        for a in normalized_articles:
            if a.get("url"):
                a["url"] = str(a["url"])
        normalized_count = len(normalized_articles)
        
        logger.info(
            "normalization_complete",
            input_count=new_count,
            output_count=normalized_count,
            filtered=new_count - normalized_count
        )
        
        # Step 6: Store raw articles to S3 (for debugging)
        if s3:
            logger.info("storing_raw_articles", count=total_fetched)
            
            raw_result = await s3.store_raw_articles(
                articles=raw_articles,  # Store all fetched (including duplicates) for audit
                query=query,
                timestamp=start_time
            )
            
            logger.info("raw_articles_stored", **raw_result)
        else:
            logger.info("s3_storage_skipped_raw", count=total_fetched, message="S3 not configured")
        
        # Step 7: Store normalized articles to S3 (Parquet for Athena)
        if s3:
            logger.info("storing_normalized_articles", count=normalized_count)
            
            normalized_result = await s3.store_normalized_articles(
                articles=normalized_articles,
                timestamp=start_time
            )
            
            logger.info("normalized_articles_stored", **normalized_result)
        else:
            logger.info("s3_storage_skipped_normalized", count=normalized_count, message="S3 not configured")
            # Log sample articles for debugging
            if normalized_articles:
                logger.info("sample_article", article=normalized_articles[0])
        
        # Step 8: Mark new hashes as processed in Redis (prevent future duplicates)
        if redis and new_hashes:
            logger.info("marking_hashes_processed", count=len(new_hashes))
            
            marked_count = await redis.batch_mark_processed(new_hashes)
            
            logger.info(
                "hashes_marked_processed",
                marked=marked_count,
                failed=len(new_hashes) - marked_count
            )
        else:
            logger.info("redis_marking_skipped", message="Redis not configured or no new hashes")
        
        # Step 9: Calculate processing time and return metrics
        end_time = datetime.now()
        processing_time_ms = int((end_time - start_time).total_seconds() * 1000)
        
        result = {
            "status": "success",
            "query": query,
            "fetched": total_fetched,
            "duplicates": duplicate_count,
            "new_articles": new_count,
            "stored": normalized_count,
            "processing_time_ms": processing_time_ms,
            "cost_savings": {
                "description": f"Skipped {duplicate_count} duplicate articles",
                "storage_saved_bytes": duplicate_count * 2000,  # Estimate 2KB per article
                "newsapi_quota_saved": 0  # We fetch before checking (could optimize)
            }
        }
        
        logger.info("ingestion_complete", **result)
        
        return result
        
    except Exception as e:
        # Log error and re-raise for SQS retry/DLQ handling
        logger.error(
            "ingestion_failed",
            query=query,
            error=str(e),
            exc_info=True
        )
        raise


def lambda_handler(event, context):
    """
    AWS Lambda handler for SQS-triggered article processing.
    
    Lambda is invoked by SQS when messages are available.
    Processes messages in batches (configured in Lambda event source mapping).
    
    Args:
        event: SQS event with records (messages)
        context: Lambda context (metadata)
    
    Returns:
        Batch processing result:
        - Success: Empty response (message deleted from queue)
        - Partial failure: Report failed message IDs (others deleted)
        - Complete failure: Raise exception (all messages return to queue)
    
    SQS Retry Behavior:
    - Failed messages return to queue
    - Retry up to 3 times (maxReceiveCount)
    - After 3 failures, move to DLQ
    - CloudWatch alarm monitors DLQ
    """
    logger.info(
        "worker_lambda_invoked",
        request_id=context.aws_request_id,
        function_name=context.function_name,
        remaining_time_ms=context.get_remaining_time_in_millis(),
        message_count=len(event.get("Records", []))
    )
    
    # SQS event contains array of records
    records = event.get("Records", [])
    
    if not records:
        logger.warning("no_sqs_records")
        return {"statusCode": 200, "body": "No messages to process"}
    
    # Process each message
    # Note: Lambda event source mapping is configured for batch_size=1
    # So we typically process one message at a time
    batch_item_failures = []
    
    for record in records:
        message_id = record["messageId"]
        
        try:
            # Parse message body (JSON string)
            message_body = json.loads(record["body"])
            
            logger.info(
                "processing_sqs_message",
                message_id=message_id,
                query=message_body.get("query", "unknown")
            )
            
            # Process the message (async operation)
            # Import asyncio here to run async function
            import asyncio
            result = asyncio.run(process_single_message(message_body))
            
            logger.info(
                "message_processed_successfully",
                message_id=message_id,
                **result
            )
            
        except json.JSONDecodeError as e:
            # Invalid JSON - log and mark as failed (will go to DLQ)
            logger.error(
                "invalid_message_json",
                message_id=message_id,
                error=str(e)
            )
            batch_item_failures.append({"itemIdentifier": message_id})
            
        except Exception as e:
            # Processing error - log and mark as failed (will retry)
            logger.error(
                "message_processing_failed",
                message_id=message_id,
                error=str(e),
                exc_info=True
            )
            batch_item_failures.append({"itemIdentifier": message_id})
    
    # Return batch processing result
    # Failed messages will be retried by SQS
    if batch_item_failures:
        logger.warning(
            "batch_partial_failure",
            failed_count=len(batch_item_failures),
            total_count=len(records)
        )
        
        # Return failed message IDs for SQS to retry
        # Successful messages are automatically deleted
        return {"batchItemFailures": batch_item_failures}
    
    else:
        logger.info(
            "batch_complete_success",
            processed_count=len(records)
        )
        
        # All messages processed successfully
        return {"statusCode": 200, "body": "Batch processed successfully"}


# Export handler for Lambda runtime
# This is the entry point specified in Terraform: app.lambda_worker_handler.lambda_handler
handler = lambda_handler
