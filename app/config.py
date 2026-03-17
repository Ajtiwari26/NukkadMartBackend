"""
Application Configuration
Manages environment variables and settings for all services
"""
from pydantic_settings import BaseSettings
from pydantic import field_validator
from functools import lru_cache
from typing import Optional, List


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Application
    APP_NAME: str = "NukkadMart"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # MongoDB Configuration
    MONGODB_URL: str = "mongodb://mongodb:27017"
    MONGODB_DATABASE: str = "nukkadmart"

    # Upstash Redis Configuration (Serverless)
    UPSTASH_REDIS_REST_URL: str = "https://teaching-sunbeam-57733.upstash.io"
    UPSTASH_REDIS_REST_TOKEN: str = ""
    REDIS_CART_TTL: int = 1800  # 30 minutes TTL for cart state
    REDIS_SESSION_TTL: int = 1800  # 30 minutes TTL for session
    REDIS_ORDER_TTL: int = 86400  # 24 hours TTL for active orders

    # Groq Configuration (Primary AI Service)
    GROQ_API_KEY: Optional[str] = None
    GROQ_VISION_MODEL: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    GROQ_TEXT_MODEL: str = "llama-3.3-70b-versatile"

    # AWS Bedrock Configuration
    # Nova Pro: Available in ap-south-1 (India) - used for OCR and intent classification
    # Nova 2 Sonic: Only available in ap-northeast-1 (Tokyo) - used for voice streaming
    AWS_REGION: str = "ap-south-1"  # Primary region for Nova Pro
    AWS_REGION_VOICE: str = "ap-northeast-1"  # Tokyo region for Nova 2 Sonic
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    BEDROCK_MODEL_ID: str = "apac.amazon.nova-pro-v1:0"  # India region model
    BEDROCK_NOVA_ACT_MODEL_ID: str = "amazon.nova-act-v1:0"
    BEDROCK_NOVA_SONIC_MODEL_ID: str = "amazon.nova-2-sonic-v1:0"  # Nova 2 Sonic (better Hindi support)

    # Voice Assistant Configuration
    ENABLE_VOICE_ASSISTANT: bool = True
    VOICE_LANGUAGE: str = "hi-IN"
    VOICE_ENABLE_CODE_SWITCHING: bool = True
    SARVAM_API_KEY: Optional[str] = None

    # S3 Configuration
    S3_BUCKET_NAME: str = "nukkadmart-images"
    S3_REGION: str = "ap-south-1"

    # Security
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS - comma-separated string that gets parsed to list
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173,http://localhost:8000,http://127.0.0.1:8000,https://*.vercel.app,https://nukkadmartweb.vercel.app"

    # Rate Limiting
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW: int = 60  # seconds

    # Nudge Engine
    ABANDONMENT_THRESHOLD: float = 0.70  # 70% probability triggers nudge
    MAX_DISCOUNT_PERCENT: float = 15.0
    MIN_DISCOUNT_PERCENT: float = 5.0

    # LLM Semantic Cache
    LLM_CACHE_ENABLED: bool = True
    LLM_CACHE_EXACT_TTL: int = 3600         # 1 hour for exact match
    LLM_CACHE_SEMANTIC_TTL: int = 3600      # 1 hour for semantic match
    LLM_CACHE_SIMILARITY_THRESHOLD: float = 0.55  # Hybrid score threshold (40% cosine + 60% keyword Jaccard)
    LLM_CACHE_MAX_ENTRIES: int = 200        # Max entries to scan for semantic match per namespace
    LLM_CACHE_EMBEDDING_DIM: int = 1024     # 1024-dim for semantic accuracy (product search uses 256)

    # Razorpay Configuration
    RAZORPAY_KEY_ID: Optional[str] = None
    RAZORPAY_KEY_SECRET: Optional[str] = None
    BYPASS_RAZORPAY: bool = False  # Set to True in development to skip actual payment

    # Google Maps Configuration
    GOOGLE_MAPS_API_KEY: Optional[str] = None

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS_ORIGINS string to list"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


settings = get_settings()
