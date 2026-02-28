"""
Store Service Router
Handles store management, onboarding, and discovery
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime
import math
import uuid
import hashlib

from app.db.mongodb import get_database
from app.config import settings
from app.core.cache import cache, TTL_NEARBY_STORES, TTL_STORE_INFO

router = APIRouter(prefix="/stores", tags=["Stores"])


# ==================== Request/Response Models ====================

class Coordinates(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


class Address(BaseModel):
    street: str
    city: str
    state: str = "Karnataka"
    pincode: str
    coordinates: Coordinates


class StoreSettings(BaseModel):
    max_discount_percent: float = Field(default=15, ge=0, le=50)
    delivery_radius_km: float = Field(default=5, ge=0)
    min_order_value: float = Field(default=100, ge=0)
    accepts_takeaway: bool = True
    accepts_delivery: bool = True
    udhaar_enabled: bool = False
    udhaar_limit: float = 5000


class QuickStoreCreate(BaseModel):
    """Simplified store creation with Google Maps location"""
    name: str
    owner_name: str
    phone: str
    city: str
    pincode: str
    street: Optional[str] = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    password: str
    google_maps_url: Optional[str] = None


class StoreResponse(BaseModel):
    store_id: str
    name: str
    owner_name: str
    phone: str
    address: dict
    status: str
    total_products: int = 0
    rating: Optional[float] = None
    distance_km: Optional[float] = None


class NearbyStoreResponse(BaseModel):
    store_id: str
    name: str
    address: str
    distance_km: float
    rating: Optional[float]
    is_open: bool
    delivery_available: bool
    min_order_value: float
    total_products: int = 0
    udhaar_enabled: bool = False


class ShopkeeperLogin(BaseModel):
    phone: str
    password: str


class SetPassword(BaseModel):
    phone: str
    new_password: str


# ==================== Helper Functions ====================

def hash_password(password: str) -> str:
    """Hash password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()


def haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate distance between two coordinates in kilometers."""
    R = 6371
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)
    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def is_store_open(store: dict) -> bool:
    """Check if store is currently open."""
    now = datetime.now()
    day = now.strftime("%A").lower()
    current_time = now.strftime("%H:%M")

    operating_hours = store.get("operating_hours", {})
    if day in operating_hours:
        hours = operating_hours[day]
        return hours.get("open", "08:00") <= current_time <= hours.get("close", "22:00")
    return True  # Default to open


# ==================== API Endpoints ====================

@router.post("/quick", response_model=StoreResponse)
async def quick_create_store(store: QuickStoreCreate):
    """Quick store registration with password and optional Google Maps location."""
    db = await get_database()

    # Check if phone already exists
    existing = await db.stores.find_one({"phone": store.phone})
    if existing:
        raise HTTPException(status_code=400, detail="Phone number already registered")

    store_id = f"STORE_{uuid.uuid4().hex[:6].upper()}"
    password_hash = hash_password(store.password)

    # Default coordinates (Bangalore) if not provided
    coords = {"lat": store.lat or 12.9716, "lng": store.lng or 77.5946}

    new_store = {
        "store_id": store_id,
        "name": store.name,
        "owner_name": store.owner_name,
        "phone": store.phone,
        "password_hash": password_hash,
        "email": None,
        "address": {
            "street": store.street or "Main Road",
            "city": store.city,
            "state": "Karnataka",
            "pincode": store.pincode,
            "coordinates": {
                "type": "Point",
                "coordinates": [coords["lng"], coords["lat"]]
            }
        },
        "google_maps_url": store.google_maps_url,
        "operating_hours": {
            "monday": {"open": "08:00", "close": "22:00"},
            "tuesday": {"open": "08:00", "close": "22:00"},
            "wednesday": {"open": "08:00", "close": "22:00"},
            "thursday": {"open": "08:00", "close": "22:00"},
            "friday": {"open": "08:00", "close": "22:00"},
            "saturday": {"open": "08:00", "close": "22:00"},
            "sunday": {"open": "09:00", "close": "21:00"}
        },
        "settings": {
            "max_discount_percent": 15,
            "delivery_radius_km": 5,
            "min_order_value": 100,
            "accepts_takeaway": True,
            "accepts_delivery": True,
            "udhaar_enabled": False,
            "udhaar_limit": 5000,
            "preparation_time_minutes": 15,
            "estimated_delivery_time_minutes": 30
        },
        "status": "ACTIVE",
        "total_products": 0,
        "rating": None,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    await db.stores.insert_one(new_store)

    # Create geospatial index if not exists
    await db.stores.create_index([("address.coordinates", "2dsphere")])

    return StoreResponse(
        store_id=store_id,
        name=store.name,
        owner_name=store.owner_name,
        phone=store.phone,
        address={
            "street": new_store["address"]["street"],
            "city": new_store["address"]["city"],
            "pincode": new_store["address"]["pincode"]
        },
        status="ACTIVE",
        total_products=0
    )


@router.post("/login")
async def shopkeeper_login(credentials: ShopkeeperLogin):
    """Shopkeeper login with phone and password."""
    db = await get_database()

    # Find store by phone
    store = await db.stores.find_one({"phone": credentials.phone})

    if not store:
        raise HTTPException(status_code=401, detail="Phone number not registered. Please register first.")

    # Check if store has password set
    if not store.get("password_hash"):
        raise HTTPException(
            status_code=401,
            detail="Password not set for this account. Please set a password first.",
            headers={"X-Password-Required": "true"}
        )

    # Verify password
    password_hash = hash_password(credentials.password)
    if store.get("password_hash") != password_hash:
        raise HTTPException(status_code=401, detail="Invalid password")

    # Count products
    product_count = await db.products.count_documents({"store_id": store["store_id"]})

    # Count orders
    order_count = await db.orders.count_documents({"store_id": store["store_id"]})

    return {
        "success": True,
        "store_id": store["store_id"],
        "name": store["name"],
        "owner_name": store["owner_name"],
        "phone": store["phone"],
        "address": store["address"],
        "settings": store.get("settings", {}),
        "status": store["status"],
        "total_products": product_count,
        "total_orders": order_count
    }


@router.post("/set-password")
async def set_store_password(data: SetPassword):
    """Set or update password for an existing store."""
    db = await get_database()

    store = await db.stores.find_one({"phone": data.phone})
    if not store:
        raise HTTPException(status_code=404, detail="Store not found with this phone number")

    password_hash = hash_password(data.new_password)

    await db.stores.update_one(
        {"phone": data.phone},
        {
            "$set": {
                "password_hash": password_hash,
                "updated_at": datetime.utcnow()
            }
        }
    )

    return {"success": True, "message": "Password updated successfully"}


@router.get("/nearby", response_model=List[NearbyStoreResponse])
async def find_nearby_stores(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(10, ge=0.1, le=50),
    limit: int = Query(20, ge=1, le=100)
):
    """Find stores near a location, sorted by distance."""
    
    # Round coordinates for cache key (2 decimal places = ~1km precision)
    lat_r = round(lat, 2)
    lng_r = round(lng, 2)
    cache_key = f"nearby_stores:{lat_r}:{lng_r}:{radius_km}:{limit}"
    
    # Check cache
    cached_data = cache.get(cache_key)
    if cached_data:
        print(f"✓ Cache hit: {cache_key}")
        return cached_data
    
    print(f"✗ Cache miss: {cache_key}")
    
    db = await get_database()

    # Get all active stores
    stores = await db.stores.find({"status": "ACTIVE"}).to_list(100)

    nearby = []
    for store in stores:
        # Get coordinates
        coords = store.get("address", {}).get("coordinates", {})
        if coords.get("type") == "Point":
            store_lng, store_lat = coords.get("coordinates", [0, 0])
        else:
            store_lat = coords.get("lat", 0)
            store_lng = coords.get("lng", 0)

        if store_lat == 0 and store_lng == 0:
            continue

        distance = haversine_distance(lat, lng, store_lat, store_lng)

        if distance <= radius_km:
            store_settings = store.get("settings", {})
            address = store.get("address", {})

            nearby.append(NearbyStoreResponse(
                store_id=store["store_id"],
                name=store["name"],
                address=f"{address.get('street', '')}, {address.get('city', '')}",
                distance_km=round(distance, 2),
                rating=store.get("rating"),
                is_open=is_store_open(store),
                delivery_available=store_settings.get("accepts_delivery", True) and distance <= store_settings.get("delivery_radius_km", 5),
                min_order_value=store_settings.get("min_order_value", 100),
                total_products=store.get("total_products", 0),
                udhaar_enabled=store_settings.get("udhaar_enabled", False)
            ))

    # Sort by distance
    nearby.sort(key=lambda x: x.distance_km)
    
    result = nearby[:limit]
    
    # Cache the result
    cache.set(cache_key, [store.dict() for store in result], TTL_NEARBY_STORES)
    print(f"✓ Cached: {cache_key} for {TTL_NEARBY_STORES}s")

    return result


@router.get("/config")
async def get_store_config():
    """Get frontend configuration including API keys."""
    return {
        "google_maps_api_key": settings.GOOGLE_MAPS_API_KEY,
        "razorpay_key_id": settings.RAZORPAY_KEY_ID
    }


@router.get("/{store_id}")
async def get_store(store_id: str):
    """Get store details by ID."""
    db = await get_database()

    store = await db.stores.find_one({"store_id": store_id})
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    # Count products
    product_count = await db.products.count_documents({"store_id": store_id})

    return {
        "store_id": store["store_id"],
        "name": store["name"],
        "owner_name": store["owner_name"],
        "phone": store["phone"],
        "address": store["address"],
        "google_maps_url": store.get("google_maps_url"),
        "operating_hours": store.get("operating_hours", {}),
        "settings": store.get("settings", {}),
        "status": store["status"],
        "total_products": product_count,
        "rating": store.get("rating")
    }


@router.put("/{store_id}/settings")
async def update_store_settings(store_id: str, store_settings: StoreSettings):
    """Update store settings including udhaar configuration."""
    db = await get_database()

    store = await db.stores.find_one({"store_id": store_id})
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    await db.stores.update_one(
        {"store_id": store_id},
        {
            "$set": {
                "settings": store_settings.model_dump(),
                "updated_at": datetime.utcnow()
            }
        }
    )

    return {"success": True, "message": "Settings updated"}

class StoreUpdate(BaseModel):
    """Schema for updating store details."""
    name: Optional[str] = None
    owner_name: Optional[str] = None
    street: Optional[str] = None
    city: Optional[str] = None
    pincode: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


@router.put("/{store_id}/update")
async def update_store(store_id: str, update_data: StoreUpdate):
    """Update store details including name, address, and location."""
    db = await get_database()

    store = await db.stores.find_one({"store_id": store_id})
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    update_fields = {}

    # Update basic fields
    if update_data.name:
        update_fields["name"] = update_data.name
    if update_data.owner_name:
        update_fields["owner_name"] = update_data.owner_name

    # Update address fields
    if any([update_data.street, update_data.city, update_data.pincode]):
        address = store.get("address", {})
        if update_data.street:
            address["street"] = update_data.street
        if update_data.city:
            address["city"] = update_data.city
        if update_data.pincode:
            address["pincode"] = update_data.pincode
        update_fields["address"] = address

    # Update coordinates if provided
    if update_data.lat is not None and update_data.lng is not None:
        if "address" not in update_fields:
            update_fields["address"] = store.get("address", {})
        update_fields["address"]["coordinates"] = {
            "type": "Point",
            "coordinates": [update_data.lng, update_data.lat]  # GeoJSON format: [lng, lat]
        }

    update_fields["updated_at"] = datetime.utcnow()

    await db.stores.update_one(
        {"store_id": store_id},
        {"$set": update_fields}
    )

    return {"success": True, "message": "Store updated successfully"}



@router.get("/{store_id}/dashboard")
async def get_store_dashboard(store_id: str):
    """Get shopkeeper dashboard with stats."""
    db = await get_database()

    store = await db.stores.find_one({"store_id": store_id})
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    # Get product stats
    total_products = await db.products.count_documents({"store_id": store_id, "is_active": True})
    low_stock = await db.products.count_documents({
        "store_id": store_id,
        "is_active": True,
        "stock_quantity": {"$lt": 10, "$gt": 0}
    })
    out_of_stock = await db.products.count_documents({
        "store_id": store_id,
        "is_active": True,
        "stock_quantity": 0
    })

    # Get order stats
    total_orders = await db.orders.count_documents({"store_id": store_id})
    pending_orders = await db.orders.count_documents({
        "store_id": store_id,
        "status": {"$in": ["PENDING", "CONFIRMED", "PREPARING"]}
    })

    # Get recent orders
    recent_orders = await db.orders.find(
        {"store_id": store_id}
    ).sort("created_at", -1).limit(10).to_list(10)

    # Calculate revenue (handle both pricing.total and total_amount fields)
    completed_orders = await db.orders.find({
        "store_id": store_id,
        "status": {"$in": ["DELIVERED", "PICKED_UP"]}  # Include both delivery and takeaway
    }).to_list(1000)
    total_revenue = sum(
        o.get("total_amount") or o.get("pricing", {}).get("total", 0)
        for o in completed_orders
    )

    return {
        "store": {
            "store_id": store["store_id"],
            "name": store["name"],
            "status": store["status"],
            "settings": store.get("settings", {})
        },
        "inventory": {
            "total_products": total_products,
            "low_stock": low_stock,
            "out_of_stock": out_of_stock
        },
        "orders": {
            "total": total_orders,
            "pending": pending_orders,
            "recent": [
                {
                    "order_id": o.get("order_id"),
                    "status": o.get("status").value if hasattr(o.get("status"), "value") else o.get("status"),
                    "total": o.get("total_amount") or o.get("pricing", {}).get("total", 0),
                    "created_at": o.get("created_at").isoformat() if isinstance(o.get("created_at"), datetime) else o.get("created_at")
                }
                for o in recent_orders
            ]
        },
        "revenue": {
            "total": total_revenue
        }
    }


@router.get("/{store_id}/products")
async def get_store_products(
    store_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100)
):
    """Get all products for a store (for shopkeeper dashboard)."""
    db = await get_database()

    skip = (page - 1) * limit

    products = await db.products.find(
        {"store_id": store_id}
    ).sort("name", 1).skip(skip).limit(limit).to_list(limit)

    total = await db.products.count_documents({"store_id": store_id})

    return {
        "products": [
            {
                "product_id": p["product_id"],
                "name": p["name"],
                "price": p["price"],
                "mrp": p.get("mrp", p["price"]),
                "stock_quantity": p.get("stock_quantity", 0),
                "category": p.get("category", ""),
                "is_active": p.get("is_active", True)
            }
            for p in products
        ],
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }


@router.get("/{store_id}/orders")
async def get_store_orders(
    store_id: str,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100)
):
    """Get orders for a store."""
    db = await get_database()

    query = {"store_id": store_id}
    if status:
        query["status"] = status

    skip = (page - 1) * limit

    orders = await db.orders.find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    total = await db.orders.count_documents(query)

    # Process orders to ensure proper serialization
    processed_orders = []
    for o in orders:
        created_at = o.get("created_at")
        accepted_at = o.get("accepted_at")

        # Convert datetime objects to ISO strings
        if isinstance(created_at, datetime):
            created_at = created_at.isoformat()
        if isinstance(accepted_at, datetime):
            accepted_at = accepted_at.isoformat()

        # Get status/fulfillment_type as string
        status = o.get("status")
        if hasattr(status, "value"):
            status = status.value
        fulfillment_type = o.get("fulfillment_type")
        if hasattr(fulfillment_type, "value"):
            fulfillment_type = fulfillment_type.value

        processed_orders.append({
            "order_id": o.get("order_id"),
            "status": status,
            "items": o.get("items", []),
            "total_amount": o.get("total_amount") or o.get("pricing", {}).get("total"),
            "pricing": o.get("pricing"),
            "fulfillment_type": fulfillment_type,
            "payment_method": o.get("payment_method"),
            "estimated_time": o.get("estimated_time"),
            "accepted_at": accepted_at,
            "distance_km": o.get("distance_km"),
            "created_at": created_at,
            "user_id": o.get("user_id"),
            "delivery_address": o.get("delivery_address")
        })

    return {
        "orders": processed_orders,
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }


# ==================== Udhaar (Credit) Management ====================

@router.get("/{store_id}/udhaar/customers")
async def get_udhaar_customers(store_id: str):
    """Get all customers with udhaar balance for a store."""
    db = await get_database()

    # Get all udhaar records for this store
    udhaar_records = await db.udhaar.find({"store_id": store_id}).to_list(100)

    customers = []
    for record in udhaar_records:
        customers.append({
            "user_id": record["user_id"],
            "user_name": record.get("user_name", "Unknown"),
            "phone": record.get("phone", ""),
            "balance": record.get("balance", 0),
            "limit": record.get("limit", 5000),
            "is_eligible": record.get("is_eligible", False),
            "total_purchases": record.get("total_purchases", 0),
            "last_payment": record.get("last_payment")
        })

    return {"customers": customers, "total": len(customers)}


@router.post("/{store_id}/udhaar/toggle-eligibility")
async def toggle_udhaar_eligibility(store_id: str, user_id: str, eligible: bool):
    """Toggle udhaar eligibility for a customer."""
    db = await get_database()

    await db.udhaar.update_one(
        {"store_id": store_id, "user_id": user_id},
        {
            "$set": {
                "is_eligible": eligible,
                "updated_at": datetime.utcnow()
            }
        },
        upsert=True
    )

    return {"success": True, "message": f"Udhaar eligibility {'enabled' if eligible else 'disabled'}"}


@router.post("/{store_id}/udhaar/record-payment")
async def record_udhaar_payment(store_id: str, user_id: str, amount: float):
    """Record a payment against udhaar balance."""
    db = await get_database()

    result = await db.udhaar.find_one_and_update(
        {"store_id": store_id, "user_id": user_id},
        {
            "$inc": {"balance": -amount},
            "$set": {
                "last_payment": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            },
            "$push": {
                "payments": {
                    "amount": amount,
                    "date": datetime.utcnow()
                }
            }
        },
        return_document=True
    )

    if not result:
        raise HTTPException(status_code=404, detail="Udhaar record not found")

    return {
        "success": True,
        "new_balance": result.get("balance", 0),
        "message": f"Payment of Rs {amount} recorded"
    }


# ==================== Store Deletion ====================

@router.delete("/{store_id}")
async def delete_store(store_id: str):
    """
    Delete a store and all its associated data (CASCADE DELETE).
    
    Deletes:
    - Store document
    - All products linked to this store
    - All inventory records
    - All orders
    - All udhaar records
    """
    db = await get_database()
    
    # Check if store exists
    store = await db.stores.find_one({"_id": store_id})
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    store_name = store.get("name", "Unknown")
    
    # Delete all associated data (CASCADE)
    products_deleted = await db.products.delete_many({"store_id": store_id})
    inventory_deleted = await db.inventory.delete_many({"store_id": store_id})
    orders_deleted = await db.orders.delete_many({"store_id": store_id})
    udhaar_deleted = await db.udhaar.delete_many({"store_id": store_id})
    
    # Delete the store itself
    await db.stores.delete_one({"_id": store_id})
    
    # Clear cache
    await cache.delete(f"store:{store_id}")
    
    return {
        "success": True,
        "message": f"Store '{store_name}' deleted successfully",
        "deleted": {
            "store": 1,
            "products": products_deleted.deleted_count,
            "inventory": inventory_deleted.deleted_count,
            "orders": orders_deleted.deleted_count,
            "udhaar": udhaar_deleted.deleted_count
        }
    }
