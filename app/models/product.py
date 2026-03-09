"""
Product Models
Pydantic schemas for products with ONDC categorization and GST compliance
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


# ==================== ONDC Category Enums ====================

class ONDCCategory(str, Enum):
    """ONDC standard categories for retail"""
    GROCERY = "Grocery"
    FRUITS_VEGETABLES = "Fruits and Vegetables"
    DAIRY = "Dairy"
    BAKERY = "Bakery"
    BEVERAGES = "Beverages"
    SNACKS = "Snacks"
    PERSONAL_CARE = "Personal Care"
    HOME_CARE = "Home Care"
    BABY_CARE = "Baby Care"
    PET_CARE = "Pet Care"
    STATIONERY = "Stationery"
    ELECTRONICS = "Electronics"
    OTHER = "Other"


class ProductUnit(str, Enum):
    """Standard product units"""
    GRAM = "g"
    KILOGRAM = "kg"
    MILLILITER = "ml"
    LITER = "L"
    PIECE = "piece"
    PACKET = "packet"
    DOZEN = "dozen"
    BOX = "box"
    BOTTLE = "bottle"
    CAN = "can"


# ==================== GST Information ====================

class GSTInfo(BaseModel):
    """GST compliance information"""
    gst_rate: float = Field(default=0, ge=0, le=28, description="GST rate percentage (0, 5, 12, 18, 28)")
    hsn_code: str = Field(..., min_length=4, max_length=8, description="HSN/SAC code")
    is_gst_inclusive: bool = Field(default=True, description="Whether price includes GST")
    cess_rate: Optional[float] = Field(default=0, ge=0, description="Additional cess if applicable")

    @property
    def cgst_rate(self) -> float:
        """Central GST rate (half of total GST)"""
        return self.gst_rate / 2

    @property
    def sgst_rate(self) -> float:
        """State GST rate (half of total GST)"""
        return self.gst_rate / 2


# ==================== ONDC Product Info ====================

class ONDCProductInfo(BaseModel):
    """ONDC protocol compliance fields"""
    category: ONDCCategory = Field(default=ONDCCategory.GROCERY)
    subcategory: Optional[str] = None
    descriptor_name: str = Field(..., description="ONDC descriptor name")
    descriptor_code: Optional[str] = Field(default=None, description="ONDC descriptor code")
    descriptor_symbol: Optional[str] = Field(default=None, description="Product symbol/image URL")
    descriptor_short_desc: Optional[str] = None
    descriptor_long_desc: Optional[str] = None

    # Fulfillment info
    fulfillment_id: Optional[str] = None
    location_id: Optional[str] = None

    # Return policy
    returnable: bool = Field(default=False)
    cancellable: bool = Field(default=True)
    return_window: Optional[str] = Field(default="P0D", description="ISO 8601 duration")

    # Seller info
    seller_pickup_return: bool = Field(default=False)
    time_to_ship: str = Field(default="PT30M", description="ISO 8601 duration - time to prepare")


# ==================== Product Schemas ====================

class ProductBase(BaseModel):
    """Base product fields"""
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=1000)
    category: str = Field(..., min_length=1)
    subcategory: Optional[str] = None
    brand: Optional[str] = None

    # Pricing
    price: float = Field(..., gt=0, description="Selling price")
    mrp: float = Field(..., gt=0, description="Maximum Retail Price")
    cost_price: Optional[float] = Field(default=None, gt=0, description="Cost price for margin calculation")

    # Units
    unit: ProductUnit = Field(default=ProductUnit.PIECE)
    unit_value: float = Field(default=1, gt=0, description="Quantity per unit (e.g., 500 for 500g)")

    # Identifiers
    barcode: Optional[str] = Field(default=None, description="EAN/UPC barcode")
    sku: Optional[str] = Field(default=None, description="Stock Keeping Unit")

    # Media
    images: List[str] = Field(default_factory=list)
    thumbnail: Optional[str] = None

    # Search & Discovery
    tags: List[str] = Field(default_factory=list)
    search_keywords: List[str] = Field(default_factory=list)


class ProductCreate(ProductBase):
    """Schema for creating a new product"""
    store_id: str
    stock_quantity: float = Field(default=0, ge=0)
    reorder_threshold: int = Field(default=10, ge=0)
    max_order_quantity: Optional[int] = Field(default=None, ge=1)

    # GST Compliance
    gst_info: GSTInfo

    # ONDC Compliance
    ondc_info: Optional[ONDCProductInfo] = None

    # Availability
    is_active: bool = Field(default=True)
    is_available: bool = Field(default=True)


class ProductUpdate(BaseModel):
    """Schema for updating product (all fields optional)"""
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    brand: Optional[str] = None
    price: Optional[float] = Field(default=None, gt=0)
    mrp: Optional[float] = Field(default=None, gt=0)
    cost_price: Optional[float] = Field(default=None, gt=0)
    unit: Optional[ProductUnit] = None
    unit_value: Optional[float] = Field(default=None, gt=0)
    barcode: Optional[str] = None
    sku: Optional[str] = None
    images: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    reorder_threshold: Optional[int] = Field(default=None, ge=0)
    max_order_quantity: Optional[int] = Field(default=None, ge=1)
    gst_info: Optional[GSTInfo] = None
    ondc_info: Optional[ONDCProductInfo] = None
    is_active: Optional[bool] = None
    is_available: Optional[bool] = None


class ProductInDB(ProductBase):
    """Product as stored in MongoDB"""
    product_id: str
    store_id: str
    stock_quantity: float = Field(default=0, ge=0)
    reorder_threshold: int = Field(default=10, ge=0)
    max_order_quantity: Optional[int] = None

    # GST & ONDC (optional for backward compatibility)
    gst_info: Optional[GSTInfo] = None
    ondc_info: Optional[ONDCProductInfo] = None

    # Status
    is_active: bool = True
    is_available: bool = True
    in_stock: bool = True

    # Timestamps
    created_at: datetime
    updated_at: datetime

    # Analytics
    total_sold: int = Field(default=0, ge=0)
    view_count: int = Field(default=0, ge=0)

    class Config:
        json_encoders = {
            datetime: lambda dt: dt.isoformat()
        }


class ProductResponse(ProductInDB):
    """Product response to client"""

    @property
    def effective_price(self) -> float:
        """Price after any active offers"""
        return self.price

    @property
    def discount_percent(self) -> float:
        """Discount percentage from MRP"""
        if self.mrp > 0:
            return round(((self.mrp - self.price) / self.mrp) * 100, 1)
        return 0


class ProductListResponse(BaseModel):
    """Paginated product list response"""
    products: List[ProductResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# ==================== Stock Management ====================

class StockOperation(str, Enum):
    """Stock update operations"""
    SET = "set"           # Set to exact value
    ADD = "add"           # Add to current
    SUBTRACT = "subtract" # Subtract from current
    RESERVE = "reserve"   # Reserve for order
    RELEASE = "release"   # Release reservation


class StockUpdate(BaseModel):
    """Stock update request"""
    quantity: float = Field(..., ge=0)
    operation: StockOperation = Field(default=StockOperation.SET)
    reason: Optional[str] = Field(default=None, description="Reason for stock change")
    reference_id: Optional[str] = Field(default=None, description="Order/procurement ID")


class StockUpdateResponse(BaseModel):
    """Stock update response"""
    product_id: str
    previous_quantity: float
    new_quantity: float
    operation: StockOperation
    in_stock: bool
    updated_at: datetime


class BulkStockUpdate(BaseModel):
    """Bulk stock update request"""
    updates: List[dict]  # [{"product_id": "...", "quantity": 10, "operation": "set"}]


# ==================== Inventory Analytics ====================

class InventoryAlert(BaseModel):
    """Low stock or out of stock alert"""
    product_id: str
    product_name: str
    current_stock: float
    reorder_threshold: int
    alert_type: str  # "low_stock" or "out_of_stock"
    days_until_stockout: Optional[int] = None


class InventorySummary(BaseModel):
    """Store inventory summary"""
    store_id: str
    total_products: int
    active_products: int
    out_of_stock_count: int
    low_stock_count: int
    total_inventory_value: float
    alerts: List[InventoryAlert]
