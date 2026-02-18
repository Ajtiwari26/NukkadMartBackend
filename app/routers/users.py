"""
User Service Router
Handles user authentication, profiles, and preferences
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
import uuid

router = APIRouter(prefix="/users", tags=["Users"])


# ==================== Request/Response Models ====================

class UserAddress(BaseModel):
    """User delivery address"""
    address_id: Optional[str] = None
    label: str = "Home"
    street: str
    city: str
    state: Optional[str] = None
    pincode: str
    coordinates: Optional[dict] = None
    is_default: bool = False


class UserPreferences(BaseModel):
    """User preferences"""
    language: str = "en"
    notifications_enabled: bool = True
    sms_notifications: bool = True
    email_notifications: bool = False


class UserRegister(BaseModel):
    """User registration request"""
    name: str = Field(..., min_length=2)
    phone: str = Field(..., pattern=r"^\+?91-?\d{10}$|^\d{10}$")
    email: Optional[EmailStr] = None
    address: Optional[UserAddress] = None


class QuickUserRegister(BaseModel):
    """Quick user registration (name + phone only)"""
    name: str = Field(..., min_length=2)
    phone: str = Field(..., min_length=10, max_length=10)


class UserLogin(BaseModel):
    """User login request"""
    phone: str
    otp: str  # In production, implement OTP verification


class UserResponse(BaseModel):
    """User profile response"""
    user_id: str
    name: str
    phone: str
    email: Optional[str]
    addresses: List[UserAddress]
    preferences: UserPreferences
    created_at: datetime


class TokenResponse(BaseModel):
    """Authentication token response"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


# ==================== Mock Data ====================

mock_users = {
    "USER_456": {
        "user_id": "USER_456",
        "name": "Priya Patel",
        "phone": "+91-9123456789",
        "email": "priya.patel@example.com",
        "addresses": [
            {
                "address_id": "ADDR_001",
                "label": "Home",
                "street": "456 Park Street",
                "city": "Bangalore",
                "state": "Karnataka",
                "pincode": "560002",
                "coordinates": {"lat": 12.9800, "lng": 77.6000},
                "is_default": True
            }
        ],
        "preferences": {
            "language": "en",
            "notifications_enabled": True,
            "sms_notifications": True,
            "email_notifications": False
        },
        "created_at": datetime(2026, 1, 20)
    }
}


# ==================== API Endpoints ====================

@router.post("/quick-register")
async def quick_register_user(user: QuickUserRegister):
    """
    Quick user registration with just name and phone.
    Used for guest checkout flow.
    
    If user with phone already exists, returns existing user.
    """
    from app.db.mongodb import get_database
    
    db = await get_database()
    
    # Check if user already exists
    existing_user = await db.users.find_one({"phone": user.phone})
    
    if existing_user:
        return {
            "user_id": existing_user["user_id"],
            "name": existing_user["name"],
            "phone": existing_user["phone"],
            "email": existing_user.get("email"),
            "total_purchases": existing_user.get("total_purchases", 0),
            "is_new": False
        }
    
    # Create new user
    user_id = f"USER_{uuid.uuid4().hex[:6].upper()}"
    
    user_doc = {
        "user_id": user_id,
        "name": user.name,
        "phone": user.phone,
        "email": None,
        "addresses": [],
        "preferences": {
            "language": "en",
            "notifications_enabled": True,
            "sms_notifications": True,
            "email_notifications": False
        },
        "total_purchases": 0,
        "total_orders": 0,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    await db.users.insert_one(user_doc)
    
    return {
        "user_id": user_id,
        "name": user.name,
        "phone": user.phone,
        "email": None,
        "total_purchases": 0,
        "is_new": True
    }


@router.post("/register", response_model=UserResponse)
async def register_user(user: UserRegister):
    """
    Register a new user.

    - Phone number is the primary identifier
    - OTP verification should be implemented in production
    """
    # Check if phone already exists
    for existing_user in mock_users.values():
        if existing_user["phone"] == user.phone:
            raise HTTPException(
                status_code=400,
                detail="Phone number already registered"
            )

    user_id = f"USER_{uuid.uuid4().hex[:6].upper()}"

    addresses = []
    if user.address:
        user.address.address_id = f"ADDR_{uuid.uuid4().hex[:6].upper()}"
        user.address.is_default = True
        addresses.append(user.address.dict())

    new_user = {
        "user_id": user_id,
        "name": user.name,
        "phone": user.phone,
        "email": user.email,
        "addresses": addresses,
        "preferences": {
            "language": "en",
            "notifications_enabled": True,
            "sms_notifications": True,
            "email_notifications": False
        },
        "created_at": datetime.utcnow()
    }

    mock_users[user_id] = new_user

    return UserResponse(**new_user)


@router.post("/login", response_model=TokenResponse)
async def login_user(credentials: UserLogin):
    """
    Authenticate user with phone + OTP.

    Returns JWT access and refresh tokens.
    """
    # Find user by phone
    user = None
    for u in mock_users.values():
        if u["phone"] == credentials.phone:
            user = u
            break

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # MOCK OTP verification - In production, verify actual OTP
    if credentials.otp != "123456":  # Mock OTP for testing
        raise HTTPException(status_code=401, detail="Invalid OTP")

    # Generate tokens (MOCK - use proper JWT in production)
    access_token = f"access_{user['user_id']}_{uuid.uuid4().hex}"
    refresh_token = f"refresh_{user['user_id']}_{uuid.uuid4().hex}"

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=900  # 15 minutes
    )


@router.post("/send-otp")
async def send_otp(phone: str):
    """
    Send OTP to phone number for authentication.

    In production, integrate with SMS gateway.
    """
    # MOCK - In production, send actual OTP via SMS
    return {
        "success": True,
        "message": f"OTP sent to {phone}",
        "expires_in": 300  # 5 minutes
    }


@router.get("/profile", response_model=UserResponse)
async def get_profile(user_id: str):
    """Get user profile."""
    if user_id not in mock_users:
        raise HTTPException(status_code=404, detail="User not found")

    return UserResponse(**mock_users[user_id])


@router.get("/{user_id}")
async def get_user_by_id(user_id: str):
    """Get user by ID from database."""
    from app.db.mongodb import get_database
    
    db = await get_database()
    user = await db.users.find_one({"user_id": user_id})
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Remove MongoDB _id field
    if "_id" in user:
        del user["_id"]
    
    return {
        "user_id": user["user_id"],
        "name": user["name"],
        "phone": user["phone"],
        "email": user.get("email"),
        "total_purchases": user.get("total_purchases", 0),
        "total_orders": user.get("total_orders", 0),
        "created_at": user.get("created_at").isoformat() if user.get("created_at") else None
    }


@router.put("/profile")
async def update_profile(user_id: str, name: Optional[str] = None, email: Optional[EmailStr] = None):
    """Update user profile details."""
    if user_id not in mock_users:
        raise HTTPException(status_code=404, detail="User not found")

    user = mock_users[user_id]

    if name:
        user["name"] = name
    if email:
        user["email"] = email

    return {"message": "Profile updated successfully", "user_id": user_id}


@router.post("/addresses")
async def add_address(user_id: str, address: UserAddress):
    """Add a new delivery address."""
    if user_id not in mock_users:
        raise HTTPException(status_code=404, detail="User not found")

    user = mock_users[user_id]

    # Generate address ID
    address.address_id = f"ADDR_{uuid.uuid4().hex[:6].upper()}"

    # If this is default, remove default from others
    if address.is_default:
        for addr in user["addresses"]:
            addr["is_default"] = False

    user["addresses"].append(address.dict())

    return {
        "message": "Address added successfully",
        "address_id": address.address_id
    }


@router.put("/addresses/{address_id}")
async def update_address(user_id: str, address_id: str, address: UserAddress):
    """Update an existing address."""
    if user_id not in mock_users:
        raise HTTPException(status_code=404, detail="User not found")

    user = mock_users[user_id]

    for i, addr in enumerate(user["addresses"]):
        if addr["address_id"] == address_id:
            address.address_id = address_id

            if address.is_default:
                for a in user["addresses"]:
                    a["is_default"] = False

            user["addresses"][i] = address.dict()
            return {"message": "Address updated successfully"}

    raise HTTPException(status_code=404, detail="Address not found")


@router.delete("/addresses/{address_id}")
async def delete_address(user_id: str, address_id: str):
    """Delete an address."""
    if user_id not in mock_users:
        raise HTTPException(status_code=404, detail="User not found")

    user = mock_users[user_id]

    for i, addr in enumerate(user["addresses"]):
        if addr["address_id"] == address_id:
            del user["addresses"][i]
            return {"message": "Address deleted successfully"}

    raise HTTPException(status_code=404, detail="Address not found")


@router.put("/preferences")
async def update_preferences(user_id: str, preferences: UserPreferences):
    """Update user preferences."""
    if user_id not in mock_users:
        raise HTTPException(status_code=404, detail="User not found")

    mock_users[user_id]["preferences"] = preferences.dict()

    return {
        "message": "Preferences updated successfully",
        "preferences": preferences
    }
