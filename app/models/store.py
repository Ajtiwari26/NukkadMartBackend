"""
Store Models
Pydantic schemas for stores with geolocation and settings
"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Dict
from datetime import datetime, time
from enum import Enum


# ==================== Enums ====================

class StoreStatus(str, Enum):
    """Store status options"""
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class StoreType(str, Enum):
    """Type of store"""
    KIRANA = "kirana"
    SUPERMARKET = "supermarket"
    PHARMACY = "pharmacy"
    BAKERY = "bakery"
    DAIRY = "dairy"
    FRUITS_VEGETABLES = "fruits_vegetables"
    GENERAL = "general"


# ==================== Location Models ====================

class GeoJSONPoint(BaseModel):
    """GeoJSON Point for MongoDB geospatial queries"""
    type: str = Field(default="Point")
    coordinates: List[float] = Field(..., min_length=2, max_length=2)  # [longitude, latitude]

    @classmethod
    def from_lat_lng(cls, lat: float, lng: float) -> "GeoJSONPoint":
        return cls(coordinates=[lng, lat])

    @property
    def latitude(self) -> float:
        return self.coordinates[1]

    @property
    def longitude(self) -> float:
        return self.coordinates[0]


class Address(BaseModel):
    """Store address with geolocation"""
    street: str = Field(..., min_length=1)
    landmark: Optional[str] = None
    city: str = Field(..., min_length=1)
    state: str = Field(..., min_length=1)
    pincode: str = Field(..., pattern=r"^\d{6}$")
    coordinates: GeoJSONPoint

    @property
    def full_address(self) -> str:
        parts = [self.street]
        if self.landmark:
            parts.append(f"Near {self.landmark}")
        parts.extend([self.city, self.state, self.pincode])
        return ", ".join(parts)


# ==================== Operating Hours ====================

class DayHours(BaseModel):
    """Operating hours for a single day"""
    is_open: bool = Field(default=True)
    open_time: str = Field(default="08:00", pattern=r"^\d{2}:\d{2}$")
    close_time: str = Field(default="22:00", pattern=r"^\d{2}:\d{2}$")
    break_start: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    break_end: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")


class OperatingHours(BaseModel):
    """Weekly operating hours"""
    monday: DayHours = Field(default_factory=DayHours)
    tuesday: DayHours = Field(default_factory=DayHours)
    wednesday: DayHours = Field(default_factory=DayHours)
    thursday: DayHours = Field(default_factory=DayHours)
    friday: DayHours = Field(default_factory=DayHours)
    saturday: DayHours = Field(default_factory=DayHours)
    sunday: DayHours = Field(default_factory=lambda: DayHours(open_time="09:00", close_time="21:00"))


# ==================== Store Settings ====================

class DeliverySettings(BaseModel):
    """Delivery configuration"""
    accepts_delivery: bool = Field(default=True)
    delivery_radius_km: float = Field(default=5.0, ge=0, le=50)
    min_order_value: float = Field(default=100, ge=0)
    delivery_fee: float = Field(default=30, ge=0)
    free_delivery_above: Optional[float] = Field(default=500, ge=0)
    estimated_delivery_time_minutes: int = Field(default=45, ge=15, le=180)


class TakeawaySettings(BaseModel):
    """Takeaway/pickup configuration"""
    accepts_takeaway: bool = Field(default=True)
    preparation_time_minutes: int = Field(default=15, ge=5, le=120)


class DiscountSettings(BaseModel):
    """Discount and nudge configuration"""
    max_discount_percent: float = Field(default=15, ge=0, le=50)
    min_discount_percent: float = Field(default=5, ge=0, le=50)
    enable_nudge_discounts: bool = Field(default=True)
    slow_moving_threshold_days: int = Field(default=30, ge=7)


class StoreSettings(BaseModel):
    """Complete store settings"""
    delivery: DeliverySettings = Field(default_factory=DeliverySettings)
    takeaway: TakeawaySettings = Field(default_factory=TakeawaySettings)
    discounts: DiscountSettings = Field(default_factory=DiscountSettings)

    # Payment settings
    accepts_cash: bool = Field(default=True)
    accepts_upi: bool = Field(default=True)
    accepts_cards: bool = Field(default=False)

    # Notifications
    order_notification_phone: Optional[str] = None
    order_notification_email: Optional[str] = None


# ==================== Store Schemas ====================

class StoreBase(BaseModel):
    """Base store fields"""
    name: str = Field(..., min_length=2, max_length=200)
    store_type: StoreType = Field(default=StoreType.KIRANA)
    description: Optional[str] = Field(default=None, max_length=500)

    # Owner info
    owner_name: str = Field(..., min_length=2)
    phone: str = Field(..., pattern=r"^\+91-?\d{10}$")
    alternate_phone: Optional[str] = Field(default=None, pattern=r"^\+91-?\d{10}$")
    email: Optional[EmailStr] = None

    # Address
    address: Address

    # Business details
    gstin: Optional[str] = Field(default=None, pattern=r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}$")
    fssai_license: Optional[str] = None
    pan_number: Optional[str] = Field(default=None, pattern=r"^[A-Z]{5}\d{4}[A-Z]{1}$")


class StoreCreate(StoreBase):
    """Schema for creating a new store"""
    operating_hours: OperatingHours = Field(default_factory=OperatingHours)
    settings: StoreSettings = Field(default_factory=StoreSettings)

    # Images
    logo_url: Optional[str] = None
    banner_url: Optional[str] = None
    store_images: List[str] = Field(default_factory=list)


class StoreUpdate(BaseModel):
    """Schema for updating store (all fields optional)"""
    name: Optional[str] = None
    store_type: Optional[StoreType] = None
    description: Optional[str] = None
    owner_name: Optional[str] = None
    phone: Optional[str] = None
    alternate_phone: Optional[str] = None
    email: Optional[EmailStr] = None
    address: Optional[Address] = None
    operating_hours: Optional[OperatingHours] = None
    settings: Optional[StoreSettings] = None
    gstin: Optional[str] = None
    fssai_license: Optional[str] = None
    logo_url: Optional[str] = None
    banner_url: Optional[str] = None
    store_images: Optional[List[str]] = None


class StoreInDB(StoreBase):
    """Store as stored in MongoDB"""
    store_id: str
    operating_hours: OperatingHours
    settings: StoreSettings

    # Status
    status: StoreStatus = Field(default=StoreStatus.PENDING_VERIFICATION)
    is_online: bool = Field(default=True)

    # Google Maps integration
    google_maps_url: Optional[str] = None
    google_place_id: Optional[str] = None

    # Images
    logo_url: Optional[str] = None
    banner_url: Optional[str] = None
    store_images: List[str] = Field(default_factory=list)

    # Stats
    rating: Optional[float] = Field(default=None, ge=0, le=5)
    total_ratings: int = Field(default=0, ge=0)
    total_orders: int = Field(default=0, ge=0)
    total_products: int = Field(default=0, ge=0)

    # Timestamps
    onboarded_at: datetime
    created_at: datetime
    updated_at: datetime

    class Config:
        json_encoders = {
            datetime: lambda dt: dt.isoformat()
        }


class StoreResponse(StoreInDB):
    """Store response to client"""
    is_open: bool = Field(default=False)

    class Config:
        json_encoders = {
            datetime: lambda dt: dt.isoformat()
        }


class NearbyStoreResponse(BaseModel):
    """Store in nearby search results"""
    store_id: str
    name: str
    store_type: StoreType
    address: str
    distance_km: float
    rating: Optional[float]
    total_ratings: int
    is_open: bool
    is_online: bool
    delivery_available: bool
    delivery_fee: float
    min_order_value: float
    estimated_delivery_minutes: int
    logo_url: Optional[str]


class StoreListResponse(BaseModel):
    """Paginated store list response"""
    stores: List[StoreResponse]
    total: int
    page: int
    page_size: int


# ==================== Store Analytics ====================

class StoreDashboard(BaseModel):
    """Store dashboard summary"""
    store_id: str
    store_name: str

    today: Dict
    this_week: Dict
    this_month: Dict

    inventory_alerts: Dict
    pending_orders: int
    active_deliveries: int

    top_products: List[Dict]
    recent_orders: List[Dict]
