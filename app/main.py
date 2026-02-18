"""
NukkadMart API Gateway
Main FastAPI application with all service routers
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
import time

from app.config import settings
from app.db.mongodb import MongoDB
from app.db.redis import RedisClient
from app.routers import (
    ocr_router,
    inventory_router,
    nudge_router,
    orders_router,
    stores_router,
    users_router,
    payments_router,
    ai_products_router
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ==================== Lifespan Events ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    # Startup
    logger.info("Starting NukkadMart API...")

    try:
        await MongoDB.connect()
        logger.info("MongoDB connected")
    except Exception as e:
        logger.warning(f"MongoDB connection failed: {e}. Running with mock data.")

    try:
        await RedisClient.connect()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}. Running with in-memory state.")

    logger.info("NukkadMart API started successfully")

    yield

    # Shutdown
    logger.info("Shutting down NukkadMart API...")
    await MongoDB.disconnect()
    await RedisClient.disconnect()
    logger.info("NukkadMart API shutdown complete")


# ==================== Create FastAPI App ====================

app = FastAPI(
    title=settings.APP_NAME,
    description="""
    NukkadMart API - AI-Powered Dark Store Platform

    ## Features

    * **OCR Service** - Upload handwritten shopping lists for AI parsing
    * **Inventory Service** - Manage store products and stock levels
    * **Nudge Engine** - AI-driven cart abandonment prevention
    * **Order Service** - Create and manage orders with real-time updates
    * **Store Service** - Store discovery and management
    * **User Service** - User authentication and profiles

    ## Authentication

    Most endpoints require authentication via JWT Bearer token.
    Use the `/api/v1/users/login` endpoint to obtain tokens.
    """,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)


# ==================== Middleware ====================

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request timing middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(round(process_time * 1000, 2))
    return response


# ==================== Exception Handlers ====================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
                "request_id": request.headers.get("X-Request-ID", "unknown")
            }
        }
    )


# ==================== Include Routers ====================

# API v1 routers
app.include_router(ocr_router, prefix=settings.API_V1_PREFIX)
app.include_router(inventory_router, prefix=settings.API_V1_PREFIX)
app.include_router(nudge_router, prefix=settings.API_V1_PREFIX)
app.include_router(orders_router, prefix=settings.API_V1_PREFIX)
app.include_router(stores_router, prefix=settings.API_V1_PREFIX)
app.include_router(users_router, prefix=settings.API_V1_PREFIX)
app.include_router(payments_router, prefix=settings.API_V1_PREFIX)
app.include_router(ai_products_router, prefix=settings.API_V1_PREFIX)


# ==================== Root Endpoints ====================

@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    health_status = {
        "status": "healthy",
        "services": {
            "api": "up",
            "mongodb": "unknown",
            "redis": "unknown"
        }
    }

    # Check MongoDB
    try:
        if MongoDB.client:
            await MongoDB.client.admin.command('ping')
            health_status["services"]["mongodb"] = "up"
        else:
            health_status["services"]["mongodb"] = "not_connected"
    except Exception:
        health_status["services"]["mongodb"] = "down"
        health_status["status"] = "degraded"

    # Check Redis (Upstash)
    try:
        if RedisClient._http_client:
            # Test with a simple GET command
            result = await RedisClient._execute("PING")
            if result == "PONG":
                health_status["services"]["redis"] = "up"
            else:
                health_status["services"]["redis"] = "degraded"
        else:
            health_status["services"]["redis"] = "not_connected"
    except Exception:
        health_status["services"]["redis"] = "down"
        health_status["status"] = "degraded"

    return health_status


@app.get("/api/v1")
async def api_v1_info():
    """API v1 information."""
    return {
        "version": "v1",
        "endpoints": {
            "ocr": f"{settings.API_V1_PREFIX}/ocr",
            "inventory": f"{settings.API_V1_PREFIX}/inventory",
            "nudge": f"{settings.API_V1_PREFIX}/nudge",
            "orders": f"{settings.API_V1_PREFIX}/orders",
            "stores": f"{settings.API_V1_PREFIX}/stores",
            "users": f"{settings.API_V1_PREFIX}/users"
        }
    }


# ==================== Run with Uvicorn ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
