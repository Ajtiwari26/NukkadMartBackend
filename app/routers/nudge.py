"""
Nudge Engine Service Router
AI-powered cart abandonment prediction and dynamic discount generation
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

from app.db.mongodb import get_database
from app.services.nudge_service import NudgeService, EventType, NudgeType

router = APIRouter(prefix="/nudge", tags=["Nudge Engine"])


# ==================== Request/Response Models ====================

class TrackEventRequest(BaseModel):
    """Request to track user behavior event"""
    session_id: str = Field(..., description="Unique session identifier")
    event_type: EventType = Field(..., description="Type of user event")
    user_id: Optional[str] = Field(None, description="User ID if authenticated")
    store_id: Optional[str] = Field(None, description="Store being browsed")
    product_id: Optional[str] = Field(None, description="Product involved in event")
    cart_value: Optional[float] = Field(None, ge=0, description="Current cart value")
    cart_items: Optional[List[dict]] = Field(None, description="Current cart items")
    duration: Optional[int] = Field(None, ge=0, description="Duration in seconds (for page views)")
    metadata: Optional[dict] = Field(None, description="Additional event data")


class TrackEventResponse(BaseModel):
    """Response after tracking event"""
    success: bool
    session_id: str
    event_type: str
    abandonment_score: float = Field(..., ge=0, le=1)
    should_nudge: bool
    cart_value: Optional[float] = None


class UpdateCartRequest(BaseModel):
    """Request to update cart state"""
    session_id: str
    cart_items: List[dict] = Field(..., description="List of cart items with product_id and quantity")
    cart_value: float = Field(..., ge=0)


class UpdateCartResponse(BaseModel):
    """Response after cart update"""
    session_id: str
    cart_value: float
    item_count: int
    abandonment_score: float


class NudgeRecommendation(BaseModel):
    """AI-generated nudge recommendation"""
    should_nudge: bool
    nudge_type: Optional[str] = None
    discount_percent: Optional[float] = None
    discount_amount: Optional[float] = None
    discount_on_products: List[str] = []
    message: Optional[str] = None
    secondary_message: Optional[str] = None
    urgency_level: Optional[str] = None
    expires_in_seconds: Optional[int] = None
    reasoning: Optional[str] = None
    offer_id: Optional[str] = None
    is_mock: bool = False


class NudgeRecommendationResponse(BaseModel):
    """Response with nudge recommendation"""
    session_id: str
    should_nudge: bool
    abandonment_probability: float
    cart_value: Optional[float] = None
    recommendation: Optional[NudgeRecommendation] = None


class ApplyOfferRequest(BaseModel):
    """Request to apply a nudge offer"""
    session_id: str
    offer_id: str
    cart_value: float = Field(..., ge=0)


class ApplyOfferResponse(BaseModel):
    """Response after applying offer"""
    success: bool
    offer_id: Optional[str] = None
    discount_applied: Optional[float] = None
    original_value: Optional[float] = None
    new_cart_value: Optional[float] = None
    message: Optional[str] = None
    error: Optional[str] = None


class NudgeAnalytics(BaseModel):
    """Nudge effectiveness analytics"""
    store_id: str
    period: str
    total_sessions: int
    nudges_triggered: int
    nudges_converted: int
    conversion_rate: float
    average_discount_given: float
    revenue_saved: float


# ==================== Dependencies ====================

async def get_nudge_service():
    """Get nudge service instance"""
    db = await get_database()
    return NudgeService(db)


# ==================== API Endpoints ====================

@router.post("/track-event", response_model=TrackEventResponse)
async def track_user_event(
    event: TrackEventRequest,
    service: NudgeService = Depends(get_nudge_service)
):
    """
    Track user behavior events for abandonment prediction.

    **Events tracked:**
    - `page_view` - User views a page
    - `product_view` - User views product details
    - `cart_add` - Item added to cart
    - `cart_remove` - Item removed from cart
    - `cart_view` - User views cart page
    - `cart_update` - Cart quantity changed
    - `checkout_start` - User starts checkout
    - `checkout_abandon` - User abandons checkout
    - `page_exit` - User attempts to leave (exit intent)
    - `discount_view` - User sees discount offer
    - `discount_apply` - User applies discount

    **Example:**
    ```python
    # Track cart addition
    requests.post("/api/v1/nudge/track-event", json={
        "session_id": "sess_abc123",
        "event_type": "cart_add",
        "product_id": "PROD_001",
        "cart_value": 450.00,
        "store_id": "STORE_123"
    })
    ```

    **Returns:**
    - `abandonment_score` - Probability of cart abandonment (0-1)
    - `should_nudge` - Whether to show a nudge to the user
    """
    event_data = {
        "user_id": event.user_id,
        "store_id": event.store_id,
        "product_id": event.product_id,
        "cart_value": event.cart_value,
        "cart_items": event.cart_items,
        "duration": event.duration,
        **(event.metadata or {})
    }

    result = await service.track_event(
        session_id=event.session_id,
        event_type=event.event_type,
        event_data=event_data
    )

    return TrackEventResponse(**result)


@router.post("/update-cart", response_model=UpdateCartResponse)
async def update_cart_state(
    request: UpdateCartRequest,
    service: NudgeService = Depends(get_nudge_service)
):
    """
    Update cart state in Redis for nudge engine monitoring.

    **Important:** Call this whenever the cart changes to keep
    the nudge engine in sync. The cart is stored in Redis with
    a TTL, allowing the nudge engine to interact with it before
    it hits the main database.

    **Example:**
    ```python
    requests.post("/api/v1/nudge/update-cart", json={
        "session_id": "sess_abc123",
        "cart_items": [
            {"product_id": "PROD_001", "quantity": 2, "price": 180},
            {"product_id": "PROD_002", "quantity": 1, "price": 56}
        ],
        "cart_value": 416.00
    })
    ```
    """
    result = await service.update_cart_state(
        session_id=request.session_id,
        cart_items=request.cart_items,
        cart_value=request.cart_value
    )

    return UpdateCartResponse(**result)


@router.get("/recommendation/{session_id}", response_model=NudgeRecommendationResponse)
async def get_nudge_recommendation(
    session_id: str,
    force: bool = Query(False, description="Force generate recommendation even below threshold"),
    service: NudgeService = Depends(get_nudge_service)
):
    """
    Get AI-powered nudge recommendation for a session.

    **Uses Amazon Nova Act to analyze:**
    - User behavior patterns (time on cart, modifications, exit intent)
    - Cart contents and value
    - Store inventory (prioritizes slow-moving items)
    - Historical conversion data

    **Returns personalized discount or incentive when:**
    - Abandonment probability >= 70%
    - User hasn't been shown 3+ nudges already

    **Response includes:**
    - `should_nudge` - Whether to show the nudge
    - `recommendation` - Discount details and messaging
    - `offer_id` - ID to use when applying the offer

    **Example flow:**
    ```
    1. Track events → /nudge/track-event
    2. Check for nudge → /nudge/recommendation/{session_id}
    3. If should_nudge, show offer to user
    4. User accepts → /nudge/apply-offer
    ```
    """
    result = await service.get_recommendation(
        session_id=session_id,
        force_generate=force
    )

    recommendation = None
    if result.get("recommendation"):
        recommendation = NudgeRecommendation(**result["recommendation"])

    return NudgeRecommendationResponse(
        session_id=result["session_id"],
        should_nudge=result.get("should_nudge", False),
        abandonment_probability=result.get("abandonment_probability", 0),
        cart_value=result.get("cart_value"),
        recommendation=recommendation
    )


@router.post("/apply-offer", response_model=ApplyOfferResponse)
async def apply_nudge_offer(
    request: ApplyOfferRequest,
    service: NudgeService = Depends(get_nudge_service)
):
    """
    Apply a nudge discount offer to the cart.

    **Validates:**
    - Offer exists and hasn't expired
    - Offer belongs to this session
    - Offer hasn't been applied already

    **Returns:**
    - Original cart value
    - Discount amount applied
    - New cart value after discount

    **Example:**
    ```python
    response = requests.post("/api/v1/nudge/apply-offer", json={
        "session_id": "sess_abc123",
        "offer_id": "offer_xyz789",
        "cart_value": 450.00
    })

    # Response:
    # {
    #     "success": true,
    #     "discount_applied": 45.00,
    #     "new_cart_value": 405.00,
    #     "message": "Congratulations! You saved Rs. 45.00!"
    # }
    ```
    """
    result = await service.apply_offer(
        session_id=request.session_id,
        offer_id=request.offer_id,
        cart_value=request.cart_value
    )

    return ApplyOfferResponse(**result)


@router.get("/analytics/{store_id}", response_model=NudgeAnalytics)
async def get_nudge_analytics(
    store_id: str,
    days: int = Query(7, ge=1, le=90, description="Number of days to analyze"),
    service: NudgeService = Depends(get_nudge_service)
):
    """
    Get nudge effectiveness analytics for a store.

    **Returns:**
    - Total sessions tracked
    - Number of nudges triggered
    - Number of nudges converted (user applied offer)
    - Conversion rate
    - Average discount given
    - Revenue saved (from converted carts)

    **Use this to:**
    - Monitor nudge engine performance
    - Adjust discount thresholds
    - Identify optimization opportunities
    """
    result = await service.get_analytics(store_id, days)
    return NudgeAnalytics(**result)


@router.get("/event-types")
async def get_event_types():
    """Get list of available event types for tracking."""
    return {
        "event_types": [
            {
                "type": e.value,
                "description": _get_event_description(e)
            }
            for e in EventType
        ]
    }


@router.get("/nudge-types")
async def get_nudge_types():
    """Get list of available nudge types."""
    return {
        "nudge_types": [
            {"type": n.value, "name": n.name.replace("_", " ").title()}
            for n in NudgeType
        ]
    }


# ==================== Helper Functions ====================

def _get_event_description(event_type: EventType) -> str:
    """Get description for event type."""
    descriptions = {
        EventType.PAGE_VIEW: "User views any page",
        EventType.PRODUCT_VIEW: "User views product details",
        EventType.CART_ADD: "Item added to cart",
        EventType.CART_REMOVE: "Item removed from cart",
        EventType.CART_VIEW: "User views cart page",
        EventType.CART_UPDATE: "Cart item quantity changed",
        EventType.CHECKOUT_START: "User starts checkout process",
        EventType.CHECKOUT_ABANDON: "User abandons checkout",
        EventType.PAGE_EXIT: "User attempts to leave (exit intent)",
        EventType.DISCOUNT_VIEW: "User sees discount offer",
        EventType.DISCOUNT_APPLY: "User applies discount code"
    }
    return descriptions.get(event_type, "")
