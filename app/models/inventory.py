"""
Inventory Models
Schemas for inventory management, stock tracking, and procurement
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime
from enum import Enum


# ==================== Enums ====================

class StockMovementType(str, Enum):
    """Types of stock movements"""
    SALE = "sale"
    RETURN = "return"
    PROCUREMENT = "procurement"
    ADJUSTMENT = "adjustment"
    DAMAGE = "damage"
    EXPIRY = "expiry"
    TRANSFER = "transfer"


class ProcurementStatus(str, Enum):
    """Procurement order status"""
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    ORDERED = "ORDERED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


# ==================== Stock Movement ====================

class StockMovement(BaseModel):
    """Record of stock change"""
    movement_id: str
    store_id: str
    product_id: str
    movement_type: StockMovementType
    quantity: float = Field(..., description="Positive for additions, negative for deductions")
    previous_quantity: float
    new_quantity: float
    reference_type: Optional[str] = None  # "order", "procurement", "manual"
    reference_id: Optional[str] = None
    notes: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StockMovementCreate(BaseModel):
    """Create stock movement record"""
    product_id: str
    movement_type: StockMovementType
    quantity: float
    reference_type: Optional[str] = None
    reference_id: Optional[str] = None
    notes: Optional[str] = None


# ==================== Inventory Snapshot ====================

class InventoryItem(BaseModel):
    """Single product inventory status"""
    product_id: str
    product_name: str
    category: str
    sku: Optional[str]
    barcode: Optional[str]
    current_stock: float
    reserved_stock: float = 0
    available_stock: float
    reorder_threshold: int
    unit: str
    price: float
    cost_price: Optional[float]
    inventory_value: float
    status: str  # "in_stock", "low_stock", "out_of_stock"
    last_sold_at: Optional[datetime]
    last_restocked_at: Optional[datetime]
    average_daily_sales: Optional[float]
    days_of_stock_remaining: Optional[int]


class InventorySnapshot(BaseModel):
    """Complete inventory snapshot for a store"""
    store_id: str
    snapshot_date: datetime

    # Summary
    total_products: int
    total_sku_count: int
    in_stock_count: int
    low_stock_count: int
    out_of_stock_count: int

    # Values
    total_inventory_value: float
    total_retail_value: float
    potential_margin: float

    # Items
    items: List[InventoryItem]

    # Alerts
    reorder_needed: List[str]  # Product IDs needing reorder
    expiring_soon: List[str]   # Product IDs expiring soon


# ==================== Procurement ====================

class ProcurementItem(BaseModel):
    """Single item in procurement order"""
    product_id: str
    product_name: str
    sku: Optional[str]
    current_stock: float
    predicted_demand: float
    recommended_quantity: float
    ordered_quantity: float = 0
    unit_cost: Optional[float]
    total_cost: Optional[float]
    supplier_sku: Optional[str]


class ProcurementOrder(BaseModel):
    """Procurement order"""
    procurement_id: str
    store_id: str
    distributor_id: Optional[str]
    distributor_name: Optional[str]

    # Items
    items: List[ProcurementItem]

    # Totals
    total_items: int
    total_quantity: float
    estimated_cost: float

    # Status
    status: ProcurementStatus

    # Dates
    created_at: datetime
    approved_at: Optional[datetime]
    ordered_at: Optional[datetime]
    expected_delivery: Optional[datetime]
    delivered_at: Optional[datetime]

    # Notes
    notes: Optional[str]
    internal_notes: Optional[str]


class ProcurementCreate(BaseModel):
    """Create procurement order"""
    store_id: str
    distributor_id: Optional[str] = None
    items: List[Dict]  # [{"product_id": "", "ordered_quantity": 10}]
    notes: Optional[str] = None


class ProcurementUpdate(BaseModel):
    """Update procurement order"""
    status: Optional[ProcurementStatus] = None
    items: Optional[List[Dict]] = None
    distributor_id: Optional[str] = None
    expected_delivery: Optional[datetime] = None
    notes: Optional[str] = None


# ==================== Demand Forecasting ====================

class DemandForecast(BaseModel):
    """Demand forecast for a product"""
    product_id: str
    product_name: str
    store_id: str

    # Historical data
    sales_last_7_days: int
    sales_last_30_days: int
    average_daily_sales: float

    # Forecast
    predicted_daily_demand: float
    predicted_weekly_demand: float
    confidence_score: float

    # Recommendations
    current_stock: float
    days_of_stock: int
    recommended_order_quantity: float
    safety_stock: float
    reorder_point: float

    # Factors
    trend: str  # "increasing", "stable", "decreasing"
    seasonality_factor: float
    day_of_week_factor: Dict[str, float]


class DemandForecastRequest(BaseModel):
    """Request for demand forecast"""
    store_id: str
    product_ids: Optional[List[str]] = None  # None = all products
    forecast_days: int = Field(default=7, ge=1, le=30)
    include_recommendations: bool = True


class DemandForecastResponse(BaseModel):
    """Demand forecast response"""
    store_id: str
    generated_at: datetime
    forecast_period_days: int
    forecasts: List[DemandForecast]

    # Summary
    total_predicted_demand_value: float
    products_needing_reorder: int
    estimated_stockout_risk: List[str]  # Product IDs at risk


# ==================== Inventory Search & Match ====================

class ProductSearchResult(BaseModel):
    """Product search result"""
    product_id: str
    name: str
    brand: Optional[str]
    category: str
    price: float
    unit: str
    in_stock: bool
    stock_quantity: float
    match_score: float
    thumbnail: Optional[str]


class ProductMatchRequest(BaseModel):
    """Request to match OCR items to products"""
    store_id: str
    items: List[Dict]  # [{"name": "rice", "quantity": 2, "unit": "kg"}]


class MatchedProduct(BaseModel):
    """Product matched from OCR/search"""
    product_id: str
    name: str
    brand: Optional[str]
    price: float
    mrp: float
    unit: str
    unit_value: float
    stock_quantity: float
    in_stock: bool
    match_confidence: float
    original_query: str
    search_term_english: Optional[str] = None  # English translation of the query
    matched_quantity: float
    line_total: float
    thumbnail: Optional[str]
    
    # Smart Matching Fields
    status: str = "perfect"  # "perfect", "size_modified", "brand_suggested", "ambiguous"
    modification_reason: Optional[str] = None
    alternatives: Optional[List[Dict]] = None  # List of alternative products when ambiguous


class ProductMatchResponse(BaseModel):
    """Product matching response"""
    store_id: str
    matched: List[MatchedProduct]
    unmatched: List[Dict]  # [{"raw_text": "...", "reason": "unreadable"}]
    suggestions: List[Dict]  # Alternative products for unmatched items
    cart_total: float
