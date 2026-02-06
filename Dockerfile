# =============================================================================
# LAMBDA CONTAINER IMAGE FOR NEWS ANALYTICS API
# =============================================================================
# This Dockerfile creates a Lambda-compatible container image.
# Uses AWS Lambda Python base image instead of standard Python image.
#
# Key Differences from ECS Dockerfile:
# - Base image: AWS Lambda Python runtime (includes Lambda runtime interface)
# - No uvicorn: Lambda runtime handles HTTP → event conversion
# - CMD: Points to Lambda handler function (not uvicorn server)
# - Multi-handler: Same image serves both API and Worker Lambdas
#
# Image Size: ~200-300MB (includes Lambda runtime + dependencies)
# Cold Start: ~1-2 seconds for first invocation

# Use AWS Lambda Python 3.11 base image
# This image includes:
# - Python 3.11 runtime
# - Lambda Runtime Interface Client (RIC)
# - AWS SDK (boto3)
# - Optimized for Lambda execution
FROM public.ecr.aws/lambda/python:3.11

# Set environment variables
# PYTHONUNBUFFERED: Send output directly to CloudWatch logs
# PYTHONDONTWRITEBYTECODE: Skip .pyc files (not needed in Lambda)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Copy requirements first for better Docker layer caching
# Docker caches layers - if requirements unchanged, this layer reused
COPY requirements.txt ${LAMBDA_TASK_ROOT}/

# Install Python dependencies into Lambda task root
# Lambda looks for packages in ${LAMBDA_TASK_ROOT}
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# Copy application code into Lambda task root
# This makes 'app' module importable
COPY ./app ${LAMBDA_TASK_ROOT}/app

# Default CMD: API handler (can be overridden in Lambda configuration)
# API Gateway invokes: app.lambda_api_handler.handler
# For worker Lambda, Terraform overrides to: app.lambda_worker_handler.handler
#
# Lambda handler format: module.function
# - module: Python file path (dots for directories)
# - function: Function name in that file
CMD ["app.lambda_api_handler.handler"]

# =============================================================================
# BUILD INSTRUCTIONS
# =============================================================================
# 
# Build and push to ECR:
# 
# 1. Authenticate with ECR:
#    aws ecr get-login-password --region us-east-1 | \
#      docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com
# 
# 2. Build image:
#    docker build -t news-analytics-api:lambda .
# 
# 3. Tag for ECR:
#    docker tag news-analytics-api:lambda \
#      <account>.dkr.ecr.us-east-1.amazonaws.com/news-analytics-dev:latest
# 
# 4. Push to ECR:
#    docker push <account>.dkr.ecr.us-east-1.amazonaws.com/news-analytics-dev:latest
# 
# 5. Lambda automatically pulls latest image on next invocation
# 
# =============================================================================
# LOCAL TESTING
# =============================================================================
# 
# Test API handler locally:
#   docker run -p 9000:8080 news-analytics-api:lambda
# 
# Send test event:
#   curl -XPOST "http://localhost:9000/2015-03-31/functions/function/invocations" \
#     -d '{"rawPath": "/health", "requestContext": {"http": {"method": "GET"}}}'
# 
# Test worker handler:
#   docker run news-analytics-api:lambda app.lambda_worker_handler.handler
#

