"""
AWS Secrets Manager helper for retrieving secrets at runtime.

This module provides a simple interface to fetch secrets from AWS Secrets Manager
with caching to minimize API calls and improve performance.
"""

import os
import json
from typing import Dict, Optional
import boto3
from botocore.exceptions import ClientError
import structlog

logger = structlog.get_logger(__name__)

# Global cache to avoid repeated Secrets Manager API calls
# Lambda containers are reused across invocations (warm starts)
_secrets_cache: Dict[str, str] = {}


def get_secret(secret_arn: str) -> str:
    """
    Retrieve a secret value from AWS Secrets Manager.
    
    Args:
        secret_arn: Full ARN of the secret
        
    Returns:
        The secret value as a string
        
    Raises:
        ClientError: If secret retrieval fails
        ValueError: If secret ARN is empty
    """
    if not secret_arn:
        raise ValueError("Secret ARN cannot be empty")
    
    # Check cache first (warm Lambda reuses containers)
    if secret_arn in _secrets_cache:
        logger.debug("secret_cache_hit", secret_arn=secret_arn)
        return _secrets_cache[secret_arn]
    
    logger.info("fetching_secret", secret_arn=secret_arn)
    
    try:
        # Create Secrets Manager client
        client = boto3.client(
            service_name='secretsmanager',
            region_name=os.getenv('AWS_REGION', 'us-east-1')
        )
        
        # Retrieve secret value
        response = client.get_secret_value(SecretId=secret_arn)
        
        # Extract secret string (handle JSON or plain text secrets)
        if 'SecretString' in response:
            secret_value = response['SecretString']
        else:
            # Binary secrets (less common)
            import base64
            secret_value = base64.b64decode(response['SecretBinary']).decode('utf-8')
        
        # Cache for future invocations
        _secrets_cache[secret_arn] = secret_value
        
        logger.info("secret_retrieved", secret_arn=secret_arn)
        return secret_value
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        logger.error(
            "secret_retrieval_failed",
            secret_arn=secret_arn,
            error_code=error_code,
            error_message=str(e)
        )
        raise


def get_secret_from_env(env_var_name: str, fallback_env_var: Optional[str] = None) -> str:
    """
    Get secret by reading ARN from environment variable, then fetching from Secrets Manager.
    
    This is the recommended pattern for Lambda functions:
    1. Store secret ARN as Lambda environment variable (e.g., NEWS_API_KEY_SECRET_ARN)
    2. Call this function to retrieve the actual secret value
    3. Optionally fall back to direct env var for local development
    
    Args:
        env_var_name: Name of env var containing the secret ARN (e.g., 'NEWS_API_KEY_SECRET_ARN')
        fallback_env_var: Name of env var with direct value for local dev (e.g., 'NEWS_API_KEY')
        
    Returns:
        The secret value
        
    Raises:
        ValueError: If neither env var is set
        ClientError: If secret retrieval fails
        
    Example:
        # In production: NEWS_API_KEY_SECRET_ARN=arn:aws:secretsmanager:...
        # In local dev: NEWS_API_KEY=abc123
        api_key = get_secret_from_env('NEWS_API_KEY_SECRET_ARN', 'NEWS_API_KEY')
    """
    # Try to get secret ARN from environment
    secret_arn = os.getenv(env_var_name)
    
    if secret_arn:
        # Production path: Fetch from Secrets Manager
        logger.debug("using_secrets_manager", env_var=env_var_name)
        return get_secret(secret_arn)
    
    # Fallback: Check for direct environment variable (local development)
    if fallback_env_var:
        direct_value = os.getenv(fallback_env_var)
        if direct_value:
            logger.debug("using_direct_env_var", env_var=fallback_env_var)
            return direct_value
    
    # Neither ARN nor fallback found
    raise ValueError(
        f"Secret not found: {env_var_name} (ARN) and {fallback_env_var} (fallback) "
        f"are both missing from environment variables"
    )


def clear_cache() -> None:
    """
    Clear the secrets cache.
    
    Useful for testing or forcing a refresh of secrets.
    In production, secrets are cached for the lifetime of the Lambda container.
    """
    global _secrets_cache
    _secrets_cache.clear()
    logger.info("secrets_cache_cleared")
