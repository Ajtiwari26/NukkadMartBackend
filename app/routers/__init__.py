# API Routers module
from .ocr import router as ocr_router
from .inventory import router as inventory_router
from .nudge import router as nudge_router
from .orders import router as orders_router
from .stores import router as stores_router
from .users import router as users_router
from .payments import router as payments_router
from .ai_products import router as ai_products_router

__all__ = [
    "ocr_router",
    "inventory_router",
    "nudge_router",
    "orders_router",
    "stores_router",
    "users_router",
    "payments_router",
    "ai_products_router"
]
