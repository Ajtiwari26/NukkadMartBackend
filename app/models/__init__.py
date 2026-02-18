# Models module - Pydantic schemas and MongoDB models

from .base import (
    MongoBaseModel,
    TimestampMixin,
    PaginationParams,
    PaginatedResponse
)

from .product import (
    # Enums
    ONDCCategory,
    ProductUnit,
    StockOperation,
    # GST & ONDC
    GSTInfo,
    ONDCProductInfo,
    # Product schemas
    ProductBase,
    ProductCreate,
    ProductUpdate,
    ProductInDB,
    ProductResponse,
    ProductListResponse,
    # Stock
    StockUpdate,
    StockUpdateResponse,
    BulkStockUpdate,
    # Analytics
    InventoryAlert,
    InventorySummary
)

from .store import (
    # Enums
    StoreStatus,
    StoreType,
    # Location
    GeoJSONPoint,
    Address,
    # Hours & Settings
    DayHours,
    OperatingHours,
    DeliverySettings,
    TakeawaySettings,
    DiscountSettings,
    StoreSettings,
    # Store schemas
    StoreBase,
    StoreCreate,
    StoreUpdate,
    StoreInDB,
    StoreResponse,
    NearbyStoreResponse,
    StoreListResponse,
    StoreDashboard
)

from .inventory import (
    # Enums
    StockMovementType,
    ProcurementStatus,
    # Stock Movement
    StockMovement,
    StockMovementCreate,
    # Inventory
    InventoryItem,
    InventorySnapshot,
    # Procurement
    ProcurementItem,
    ProcurementOrder,
    ProcurementCreate,
    ProcurementUpdate,
    # Demand Forecasting
    DemandForecast,
    DemandForecastRequest,
    DemandForecastResponse,
    # Search & Match
    ProductSearchResult,
    ProductMatchRequest,
    MatchedProduct,
    ProductMatchResponse
)

__all__ = [
    # Base
    "MongoBaseModel",
    "TimestampMixin",
    "PaginationParams",
    "PaginatedResponse",
    # Product
    "ONDCCategory",
    "ProductUnit",
    "StockOperation",
    "GSTInfo",
    "ONDCProductInfo",
    "ProductBase",
    "ProductCreate",
    "ProductUpdate",
    "ProductInDB",
    "ProductResponse",
    "ProductListResponse",
    "StockUpdate",
    "StockUpdateResponse",
    "BulkStockUpdate",
    "InventoryAlert",
    "InventorySummary",
    # Store
    "StoreStatus",
    "StoreType",
    "GeoJSONPoint",
    "Address",
    "DayHours",
    "OperatingHours",
    "DeliverySettings",
    "TakeawaySettings",
    "DiscountSettings",
    "StoreSettings",
    "StoreBase",
    "StoreCreate",
    "StoreUpdate",
    "StoreInDB",
    "StoreResponse",
    "NearbyStoreResponse",
    "StoreListResponse",
    "StoreDashboard",
    # Inventory
    "StockMovementType",
    "ProcurementStatus",
    "StockMovement",
    "StockMovementCreate",
    "InventoryItem",
    "InventorySnapshot",
    "ProcurementItem",
    "ProcurementOrder",
    "ProcurementCreate",
    "ProcurementUpdate",
    "DemandForecast",
    "DemandForecastRequest",
    "DemandForecastResponse",
    "ProductSearchResult",
    "ProductMatchRequest",
    "MatchedProduct",
    "ProductMatchResponse"
]
