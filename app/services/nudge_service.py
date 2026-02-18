"""
Nudge Engine Service
AI-powered cart abandonment prediction and dynamic discount generation
"""
import uuid
import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from enum import Enum

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.services.ai_service import AIService, get_ai_service
from app.db.redis import RedisClient
from app.config import settings

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """User behavior event types"""
    PAGE_VIEW = "page_view"
    PRODUCT_VIEW = "product_view"
    CART_ADD = "cart_add"
    CART_REMOVE = "cart_remove"
    CART_VIEW = "cart_view"
    CART_UPDATE = "cart_update"
    CHECKOUT_START = "checkout_start"
    CHECKOUT_ABANDON = "checkout_abandon"
    PAGE_EXIT = "page_exit"
    DISCOUNT_VIEW = "discount_view"
    DISCOUNT_APPLY = "discount_apply"


class NudgeType(str, Enum):
    """Types of nudges"""
    DISCOUNT = "discount"
    FREE_DELIVERY = "free_delivery"
    URGENCY = "urgency"
    SOCIAL_PROOF = "social_proof"
    BUNDLE = "bundle"


class NudgeService:
    """Service for cart abandonment prediction and nudge generation"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.sessions = db.nudge_sessions
        self.nudge_history = db.nudge_history
        self.offers = db.nudge_offers
        self.ai = get_ai_service()

    # ==================== Session Management ====================

    async def create_or_update_session(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        store_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create or update a user session for tracking."""
        now = datetime.utcnow()

        # Check Redis first
        session = await self._get_redis_session(session_id)

        if not session:
            session = {
                "session_id": session_id,
                "user_id": user_id,
                "store_id": store_id,
                "cart_items": [],
                "cart_value": 0,
                "events": [],
                "page_views": 0,
                "cart_modifications": 0,
                "checkout_attempts": 0,
                "time_on_cart_seconds": 0,
                "abandonment_score": 0.0,
                "nudges_shown": 0,
                "nudges_converted": 0,
                "created_at": now.isoformat(),
                "last_activity": now.isoformat()
            }
        else:
            session["last_activity"] = now.isoformat()
            if user_id:
                session["user_id"] = user_id
            if store_id:
                session["store_id"] = store_id

        # Store in Redis
        await self._set_redis_session(session_id, session)

        return session

    async def track_event(
        self,
        session_id: str,
        event_type: EventType,
        event_data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Track a user behavior event and update abandonment score.

        Args:
            session_id: User session ID
            event_type: Type of event
            event_data: Additional event data (product_id, cart_value, etc.)

        Returns:
            Updated session with abandonment score and nudge decision
        """
        now = datetime.utcnow()
        event_data = event_data or {}

        # Get or create session
        session = await self._get_redis_session(session_id)
        if not session:
            session = await self.create_or_update_session(
                session_id,
                user_id=event_data.get("user_id"),
                store_id=event_data.get("store_id")
            )

        # Record event
        event = {
            "type": event_type.value,
            "timestamp": now.isoformat(),
            "data": event_data
        }
        session["events"].append(event)

        # Keep only last 50 events
        if len(session["events"]) > 50:
            session["events"] = session["events"][-50:]

        # Update session metrics based on event type
        session = self._update_session_metrics(session, event_type, event_data)

        # Calculate abandonment probability
        abandonment_score = self._calculate_abandonment_probability(session)
        session["abandonment_score"] = abandonment_score

        # Check if we should trigger a nudge
        should_nudge = self._should_trigger_nudge(session, event_type)

        # Update session in Redis
        session["last_activity"] = now.isoformat()
        await self._set_redis_session(session_id, session)

        return {
            "success": True,
            "session_id": session_id,
            "event_type": event_type.value,
            "abandonment_score": round(abandonment_score, 2),
            "should_nudge": should_nudge,
            "cart_value": session.get("cart_value", 0)
        }

    async def update_cart_state(
        self,
        session_id: str,
        cart_items: List[Dict],
        cart_value: float
    ) -> Dict[str, Any]:
        """
        Update the cart state in Redis for nudge monitoring.

        This is the key method for the nudge engine to interact with
        cart state before it hits the main database.
        """
        session = await self._get_redis_session(session_id)
        if not session:
            session = await self.create_or_update_session(session_id)

        previous_value = session.get("cart_value", 0)
        previous_items = len(session.get("cart_items", []))

        session["cart_items"] = cart_items
        session["cart_value"] = cart_value
        session["last_activity"] = datetime.utcnow().isoformat()

        # Track cart modification
        if len(cart_items) != previous_items or cart_value != previous_value:
            session["cart_modifications"] = session.get("cart_modifications", 0) + 1

        # Recalculate abandonment score
        session["abandonment_score"] = self._calculate_abandonment_probability(session)

        await self._set_redis_session(session_id, session)

        return {
            "session_id": session_id,
            "cart_value": cart_value,
            "item_count": len(cart_items),
            "abandonment_score": round(session["abandonment_score"], 2)
        }

    # ==================== Nudge Generation ====================

    async def get_recommendation(
        self,
        session_id: str,
        force_generate: bool = False
    ) -> Dict[str, Any]:
        """
        Get AI-powered nudge recommendation for a session.

        Uses Amazon Nova Act to analyze:
        - User behavior patterns
        - Cart contents
        - Store inventory (slow-moving items)
        - Historical conversion data
        """
        session = await self._get_redis_session(session_id)
        if not session:
            return {
                "session_id": session_id,
                "should_nudge": False,
                "reason": "Session not found"
            }

        abandonment_score = session.get("abandonment_score", 0)

        # Check if nudge is warranted
        if not force_generate and abandonment_score < settings.ABANDONMENT_THRESHOLD:
            return {
                "session_id": session_id,
                "should_nudge": False,
                "abandonment_probability": abandonment_score,
                "reason": f"Abandonment score {abandonment_score:.2f} below threshold {settings.ABANDONMENT_THRESHOLD}"
            }

        # Check if we've shown too many nudges
        if session.get("nudges_shown", 0) >= 3:
            return {
                "session_id": session_id,
                "should_nudge": False,
                "reason": "Maximum nudges reached for this session"
            }

        # Get slow-moving products from cart
        slow_moving = await self._get_slow_moving_products(session)

        # Get store settings
        store_settings = await self._get_store_settings(session.get("store_id"))

        # Generate recommendation using AI service
        recommendation = await self.ai.generate_nudge_recommendation(
            cart_items=session.get("cart_items", []),
            user_behavior={
                "time_on_cart": session.get("time_on_cart_seconds", 0),
                "cart_modifications": session.get("cart_modifications", 0),
                "exit_intent": self._has_exit_intent(session),
                "abandonment_score": abandonment_score,
                "checkout_attempts": session.get("checkout_attempts", 0)
            },
            slow_moving_products=slow_moving,
            store_settings=store_settings
        )

        # Create and store offer if nudge is recommended
        if recommendation.get("should_nudge", False):
            offer = await self._create_offer(session_id, recommendation)
            recommendation["offer_id"] = offer["offer_id"]

            # Update session
            session["nudges_shown"] = session.get("nudges_shown", 0) + 1
            await self._set_redis_session(session_id, session)

        return {
            "session_id": session_id,
            "should_nudge": recommendation.get("should_nudge", False),
            "abandonment_probability": abandonment_score,
            "cart_value": session.get("cart_value", 0),
            "recommendation": recommendation
        }

    async def apply_offer(
        self,
        session_id: str,
        offer_id: str,
        cart_value: float
    ) -> Dict[str, Any]:
        """
        Apply a nudge discount offer to the cart.

        Validates offer and calculates final discount.
        """
        # Get offer from database
        offer = await self.offers.find_one({"offer_id": offer_id})

        if not offer:
            return {"success": False, "error": "Offer not found or expired"}

        if offer.get("applied"):
            return {"success": False, "error": "Offer already applied"}

        if offer.get("session_id") != session_id:
            return {"success": False, "error": "Offer not valid for this session"}

        # Check expiry
        expires_at = offer.get("expires_at")
        if expires_at and datetime.fromisoformat(expires_at) < datetime.utcnow():
            return {"success": False, "error": "Offer has expired"}

        # Calculate discount
        discount_percent = offer.get("discount_percent", 0)
        discount_amount = offer.get("discount_amount", 0)

        if discount_percent > 0:
            discount = cart_value * (discount_percent / 100)
        else:
            discount = min(discount_amount, cart_value * 0.15)  # Cap at 15%

        new_cart_value = cart_value - discount

        # Mark offer as applied
        now = datetime.utcnow()
        await self.offers.update_one(
            {"offer_id": offer_id},
            {
                "$set": {
                    "applied": True,
                    "applied_at": now,
                    "cart_value_before": cart_value,
                    "discount_applied": discount,
                    "cart_value_after": new_cart_value
                }
            }
        )

        # Update session
        session = await self._get_redis_session(session_id)
        if session:
            session["nudges_converted"] = session.get("nudges_converted", 0) + 1
            await self._set_redis_session(session_id, session)

        # Track conversion event
        await self.track_event(
            session_id,
            EventType.DISCOUNT_APPLY,
            {"offer_id": offer_id, "discount": discount}
        )

        logger.info(f"Offer {offer_id} applied. Discount: {discount:.2f}")

        return {
            "success": True,
            "offer_id": offer_id,
            "discount_applied": round(discount, 2),
            "original_value": round(cart_value, 2),
            "new_cart_value": round(new_cart_value, 2),
            "message": f"Congratulations! You saved Rs. {discount:.2f}!"
        }

    # ==================== Analytics ====================

    async def get_analytics(self, store_id: str, days: int = 7) -> Dict[str, Any]:
        """Get nudge effectiveness analytics for a store."""
        since = datetime.utcnow() - timedelta(days=days)

        # Aggregate from nudge_history
        pipeline = [
            {
                "$match": {
                    "store_id": store_id,
                    "created_at": {"$gte": since}
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total_sessions": {"$sum": 1},
                    "nudges_triggered": {
                        "$sum": {"$cond": [{"$gt": ["$nudges_shown", 0]}, 1, 0]}
                    },
                    "nudges_converted": {"$sum": "$nudges_converted"},
                    "total_discount_given": {"$sum": "$discount_applied"},
                    "total_revenue_saved": {"$sum": "$cart_value_after"}
                }
            }
        ]

        result = await self.nudge_history.aggregate(pipeline).to_list(1)
        stats = result[0] if result else {}

        nudges_triggered = stats.get("nudges_triggered", 0)
        nudges_converted = stats.get("nudges_converted", 0)

        return {
            "store_id": store_id,
            "period": f"last_{days}_days",
            "total_sessions": stats.get("total_sessions", 0),
            "nudges_triggered": nudges_triggered,
            "nudges_converted": nudges_converted,
            "conversion_rate": round(nudges_converted / nudges_triggered, 3) if nudges_triggered > 0 else 0,
            "average_discount_given": round(stats.get("total_discount_given", 0) / max(nudges_converted, 1), 2),
            "revenue_saved": round(stats.get("total_revenue_saved", 0), 2)
        }

    # ==================== Private Methods ====================

    async def _get_redis_session(self, session_id: str) -> Optional[Dict]:
        """Get session from Redis."""
        try:
            data = await RedisClient.get_session(session_id)
            return data
        except Exception as e:
            logger.warning(f"Redis session fetch failed: {e}")
            return None

    async def _set_redis_session(self, session_id: str, session: Dict) -> None:
        """Store session in Redis."""
        try:
            await RedisClient.set_session(session_id, session)
        except Exception as e:
            logger.warning(f"Redis session store failed: {e}")

    def _update_session_metrics(
        self,
        session: Dict,
        event_type: EventType,
        event_data: Dict
    ) -> Dict:
        """Update session metrics based on event."""
        if event_type == EventType.PAGE_VIEW:
            session["page_views"] = session.get("page_views", 0) + 1

        elif event_type == EventType.CART_VIEW:
            duration = event_data.get("duration") or 0
            session["time_on_cart_seconds"] = session.get("time_on_cart_seconds", 0) + duration

        elif event_type in [EventType.CART_ADD, EventType.CART_REMOVE, EventType.CART_UPDATE]:
            session["cart_modifications"] = session.get("cart_modifications", 0) + 1
            if "cart_value" in event_data:
                session["cart_value"] = event_data["cart_value"]
            if "cart_items" in event_data:
                session["cart_items"] = event_data["cart_items"]

        elif event_type == EventType.CHECKOUT_START:
            session["checkout_attempts"] = session.get("checkout_attempts", 0) + 1

        elif event_type == EventType.CHECKOUT_ABANDON:
            session["checkout_attempts"] = session.get("checkout_attempts", 0) + 1

        return session

    def _calculate_abandonment_probability(self, session: Dict) -> float:
        """
        Calculate cart abandonment probability based on user behavior.

        Factors:
        - Time spent on cart page
        - Number of cart modifications
        - Exit intent signals
        - Checkout attempts without completion
        - Cart value patterns
        """
        score = 0.3  # Base probability

        # Cart modifications (more mods = higher indecision)
        cart_mods = session.get("cart_modifications", 0)
        if cart_mods > 5:
            score += 0.2
        elif cart_mods > 2:
            score += 0.1

        # Page views without checkout
        page_views = session.get("page_views", 0)
        checkout_attempts = session.get("checkout_attempts", 0)
        if page_views > 5 and checkout_attempts == 0:
            score += 0.15

        # Time on cart (longer = more hesitation)
        time_on_cart = session.get("time_on_cart_seconds", 0)
        if time_on_cart > 180:  # 3+ minutes
            score += 0.15
        elif time_on_cart > 60:  # 1+ minute
            score += 0.05

        # Exit intent events
        if self._has_exit_intent(session):
            score += 0.25

        # Checkout abandonment is highest signal
        events = session.get("events", [])
        abandon_events = [e for e in events if e.get("type") == EventType.CHECKOUT_ABANDON.value]
        if abandon_events:
            score += 0.3

        # Multiple checkout attempts without success
        if checkout_attempts > 1:
            score += 0.1

        return min(score, 1.0)

    def _has_exit_intent(self, session: Dict) -> bool:
        """Check if user has shown exit intent."""
        events = session.get("events", [])
        exit_events = [e for e in events if e.get("type") == EventType.PAGE_EXIT.value]
        return len(exit_events) > 0

    def _should_trigger_nudge(self, session: Dict, event_type: EventType) -> bool:
        """Determine if we should trigger a nudge."""
        abandonment_score = session.get("abandonment_score", 0)

        # Only trigger on specific high-intent events
        trigger_events = [
            EventType.PAGE_EXIT,
            EventType.CART_VIEW,
            EventType.CHECKOUT_ABANDON
        ]

        if event_type not in trigger_events:
            return False

        # Check abandonment threshold
        if abandonment_score < settings.ABANDONMENT_THRESHOLD:
            return False

        # Don't spam nudges
        if session.get("nudges_shown", 0) >= 3:
            return False

        return True

    async def _get_slow_moving_products(self, session: Dict) -> List[Dict]:
        """Get slow-moving products from the user's cart."""
        cart_items = session.get("cart_items", [])
        store_id = session.get("store_id")

        if not cart_items or not store_id:
            return []

        # Query products with low sales velocity
        product_ids = [item.get("product_id") for item in cart_items if item.get("product_id")]

        slow_moving = []
        products_collection = self.db.products

        for product_id in product_ids:
            product = await products_collection.find_one({"product_id": product_id})
            if product:
                # Check if product is slow-moving (low total_sold or high stock)
                total_sold = product.get("total_sold", 0)
                stock = product.get("stock_quantity", 0)

                # Simple heuristic: high stock + low sales = slow moving
                if stock > 50 and total_sold < 10:
                    slow_moving.append({
                        "product_id": product_id,
                        "name": product.get("name"),
                        "stock": stock,
                        "total_sold": total_sold
                    })

        return slow_moving

    async def _get_store_settings(self, store_id: Optional[str]) -> Dict:
        """Get store discount settings."""
        if not store_id:
            return {
                "max_discount_percent": settings.MAX_DISCOUNT_PERCENT,
                "min_discount_percent": settings.MIN_DISCOUNT_PERCENT
            }

        store = await self.db.stores.find_one({"store_id": store_id})
        if store and "settings" in store:
            discount_settings = store["settings"].get("discounts", {})
            return {
                "max_discount_percent": discount_settings.get("max_discount_percent", settings.MAX_DISCOUNT_PERCENT),
                "min_discount_percent": discount_settings.get("min_discount_percent", settings.MIN_DISCOUNT_PERCENT)
            }

        return {
            "max_discount_percent": settings.MAX_DISCOUNT_PERCENT,
            "min_discount_percent": settings.MIN_DISCOUNT_PERCENT
        }

    async def _create_offer(self, session_id: str, recommendation: Dict) -> Dict:
        """Create and store a nudge offer."""
        offer_id = f"offer_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow()
        expires_in = recommendation.get("expires_in_seconds", 300)

        offer = {
            "offer_id": offer_id,
            "session_id": session_id,
            "nudge_type": recommendation.get("nudge_type", "discount"),
            "discount_percent": recommendation.get("discount_percent", 0),
            "discount_amount": recommendation.get("discount_amount", 0),
            "discount_on_products": recommendation.get("discount_on_products", []),
            "message": recommendation.get("message", ""),
            "secondary_message": recommendation.get("secondary_message", ""),
            "urgency_level": recommendation.get("urgency_level", "medium"),
            "expires_at": (now + timedelta(seconds=expires_in)).isoformat(),
            "applied": False,
            "created_at": now,
            "is_mock": recommendation.get("is_mock", False)
        }

        await self.offers.insert_one(offer)

        return offer
