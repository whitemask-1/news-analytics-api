from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings): # App config settings loaded from environment variables
#In dev, read from .env file
#In prod, read from ECS task env or Systems Manager

    #Application setting
    app_name: str = "News Analytics API"
    environment: str = "development"
    log_level: str = "INFO"

    #External APIs
    news_api_key: str
    news_api_base_url: str = "https://newsapi.org/v2"

    #AWS
    aws_region: str = "us-east-1"
    s3_bucket_name: str = "news-analytics-bucket"


    class Config:
        env_file = ".env"  # Load variables from a .env file if present
        env_file_encoding = 'utf-8'
        case_sensitive = False

settings = Settings()  # Instantiate settings to be used throughout the app