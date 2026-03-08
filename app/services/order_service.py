"""
Order Service
Handles order creation, management, and real-time updates via WebSocket
"""
import uuid
import json
import asyncio
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import WebSocket

from app.db.redis import RedisClient
from app.services.inventory_service import InventoryService
from app.models.product import StockUpdate, StockOperation

logger = logging.getLogger(__name__)


class OrderStatus(str, Enum):
    """Order status state machine"""
    CREATED = "CREATED"
    CONFIRMED = "CONFIRMED"
    PREPARING = "PREPARING"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class FulfillmentType(str, Enum):
    """Order fulfillment types"""
    TAKEAWAY = "TAKEAWAY"
    DELIVERY = "DELIVERY"


# Valid status transitions
STATUS_TRANSITIONS = {
    OrderStatus.CREATED: [OrderStatus.CONFIRMED, OrderStatus.CANCELLED],
    OrderStatus.CONFIRMED: [OrderStatus.PREPARING, OrderStatus.CANCELLED],
    OrderStatus.PREPARING: [OrderStatus.READY, OrderStatus.CANCELLED],
    OrderStatus.READY: [OrderStatus.PICKED_UP, OrderStatus.OUT_FOR_DELIVERY],
    OrderStatus.OUT_FOR_DELIVERY: [OrderStatus.DELIVERED],
    OrderStatus.PICKED_UP: [],
    OrderStatus.DELIVERED: [],
    OrderStatus.CANCELLED: []
}


class WebSocketManager:
    """
    Manages WebSocket connections for real-time order updates.
    Uses Redis Pub/Sub for scalability across multiple server instances.
    """

    def __init__(self):
        # Local connections for this server instance
        self.connections: Dict[str, Dict[str, WebSocket]] = {
            "customers": {},    # user_id -> WebSocket
            "stores": {},       # store_id -> WebSocket
            "riders": {}        # rider_id -> WebSocket
        }
        self._pubsub_task = None

    async def start_pubsub_listener(self):
        """Start listening to Redis Pub/Sub for order updates."""
        try:
            pubsub = RedisClient.client.pubsub()
            await pubsub.subscribe("order_updates")
            self._pubsub_task = asyncio.create_task(self._listen_pubsub(pubsub))
            logger.info("WebSocket Pub/Sub listener started")
        except Exception as e:
            logger.warning(f"Failed to start Pub/Sub listener: {e}")

    async def stop_pubsub_listener(self):
        """Stop the Pub/Sub listener."""
        if self._pubsub_task:
            self._pubsub_task.cancel()

    async def _listen_pubsub(self, pubsub):
        """Listen for messages on the order_updates channel."""
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        await self._handle_pubsub_message(data)
                    except json.JSONDecodeError:
                        pass
        except asyncio.CancelledError:
            await pubsub.unsubscribe("order_updates")
        except Exception as e:
            logger.error(f"Pub/Sub listener error: {e}")

    async def _handle_pubsub_message(self, data: Dict):
        """Handle a message received from Pub/Sub."""
        message_type = data.get("type")

        if message_type == "order_update":
            # Send to relevant local connections
            user_id = data.get("user_id")
            store_id = data.get("store_id")
            rider_id = data.get("rider_id")

            notification = {
                "type": "order_update",
                "order_id": data.get("order_id"),
                "status": data.get("status"),
                "updated_at": data.get("updated_at")
            }

            if user_id and user_id in self.connections["customers"]:
                await self._safe_send(self.connections["customers"][user_id], notification)

            if store_id and store_id in self.connections["stores"]:
                await self._safe_send(self.connections["stores"][store_id], notification)

            if rider_id and rider_id in self.connections["riders"]:
                await self._safe_send(self.connections["riders"][rider_id], notification)

    async def connect(self, websocket: WebSocket, role: str, entity_id: str):
        """Accept and register a WebSocket connection."""
        await websocket.accept()

        if role not in self.connections:
            self.connections[role] = {}

        self.connections[role][entity_id] = websocket
        logger.info(f"WebSocket connected: {role}/{entity_id}")

    def disconnect(self, role: str, entity_id: str):
        """Remove a WebSocket connection."""
        if role in self.connections and entity_id in self.connections[role]:
            del self.connections[role][entity_id]
            logger.info(f"WebSocket disconnected: {role}/{entity_id}")

    async def broadcast_order_update(self, order: Dict):
        """
        Broadcast order update to all relevant parties.
        Publishes to Redis for cross-instance communication.
        """
        message = {
            "type": "order_update",
            "order_id": order["order_id"],
            "user_id": order["user_id"],
            "store_id": order["store_id"],
            "rider_id": order.get("rider_id"),
            "status": order["status"],
            "updated_at": order["updated_at"].isoformat() if isinstance(order["updated_at"], datetime) else order["updated_at"]
        }

        # Publish to Redis for all server instances
        try:
            await RedisClient.publish("order_updates", message)
        except Exception as e:
            logger.warning(f"Redis publish failed: {e}")
            # Fallback to local broadcast
            await self._local_broadcast(message)

    async def _local_broadcast(self, message: Dict):
        """Broadcast to local connections only."""
        notification = {
            "type": "order_update",
            "order_id": message.get("order_id"),
            "status": message.get("status"),
            "updated_at": message.get("updated_at")
        }

        user_id = message.get("user_id")
        store_id = message.get("store_id")
        rider_id = message.get("rider_id")

        if user_id and user_id in self.connections["customers"]:
            await self._safe_send(self.connections["customers"][user_id], notification)

        if store_id and store_id in self.connections["stores"]:
            await self._safe_send(self.connections["stores"][store_id], notification)

        if rider_id and rider_id in self.connections["riders"]:
            await self._safe_send(self.connections["riders"][rider_id], notification)

    async def send_to_user(self, user_id: str, message: Dict):
        """Send message to specific customer."""
        if user_id in self.connections["customers"]:
            await self._safe_send(self.connections["customers"][user_id], message)

    async def send_to_store(self, store_id: str, message: Dict):
        """Send message to store/shopkeeper."""
        if store_id in self.connections["stores"]:
            await self._safe_send(self.connections["stores"][store_id], message)

    async def send_to_rider(self, rider_id: str, message: Dict):
        """Send message to delivery rider."""
        if rider_id in self.connections["riders"]:
            await self._safe_send(self.connections["riders"][rider_id], message)

    async def _safe_send(self, websocket: WebSocket, message: Dict):
        """Safely send message, handling connection errors."""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.warning(f"WebSocket send failed: {e}")


# Global WebSocket manager instance
ws_manager = WebSocketManager()


class OrderService:
    """Service for order management"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.orders = db.orders
        self.inventory_service = InventoryService(db)

    def _calculate_delivery_fee(self, order_value: float, distance_km: float) -> float:
        """
        Calculate delivery fee based on order value and distance.
        - Free delivery for orders >= Rs 199 (encourage local shopping)
        - Max delivery fee capped at Rs 40
        """
        import math

        Ov = order_value
        dist = distance_km

        # Free delivery for orders >= Rs 199
        if Ov >= 199:
            return 0.0

        # Minimum distance
        if dist < 0.8:
            dist = 0.8

        # Base delivery fee calculation
        # Distance-based charge (simplified)
        if dist <= 2:
            distance_charge = 10
        elif dist <= 4:
            distance_charge = 15
        else:
            distance_charge = 20 + (dist - 4) * 3

        # Order value based charge (lower orders = higher charge)
        if Ov < 50:
            value_charge = 20
        elif Ov < 100:
            value_charge = 15
        elif Ov < 150:
            value_charge = 10
        else:
            value_charge = 5

        # Total delivery fee
        delivery_fee = distance_charge + value_charge

        # Cap delivery fee at Rs 40
        if delivery_fee > 40:
            delivery_fee = 40

        # Minimum delivery fee Rs 15
        if delivery_fee < 15:
            delivery_fee = 15

        return round(delivery_fee, 2)

    async def create_order(
        self,
        user_id: str,
        store_id: str,
        items: List[Dict],
        fulfillment_type: FulfillmentType,
        delivery_address: Optional[Dict] = None,
        applied_discount: float = 0,
        session_id: Optional[str] = None,
        payment_method: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new order.

        - Validates cart items
        - Checks inventory availability
        - Reserves stock
        - Calculates final pricing
        - Creates order in database
        - Broadcasts to WebSocket
        """
        # Generate order ID
        order_id = f"ORD_{datetime.utcnow().strftime('%Y%m%d')}_{uuid.uuid4().hex[:6].upper()}"
        now = datetime.utcnow()

        # Validate items exist and have stock
        validated_items = []
        subtotal = 0

        for item in items:
            product_id = item.get("product_id")
            quantity = item.get("quantity", 1)

            # Get product from inventory
            product = await self.inventory_service.get_product(product_id)
            if not product:
                raise ValueError(f"Product {product_id} not found")

            if product.stock_quantity < quantity:
                raise ValueError(f"Insufficient stock for {product.name}. Available: {product.stock_quantity}")

            unit_price = product.price
            item_subtotal = unit_price * quantity
            subtotal += item_subtotal

            validated_items.append({
                "product_id": product_id,
                "name": product.name,
                "quantity": quantity,
                "unit_price": unit_price,
                "subtotal": item_subtotal
            })

            # Reserve stock
            await self.inventory_service.update_stock(
                product_id,
                StockUpdate(
                    quantity=quantity,
                    operation=StockOperation.RESERVE,
                    reason="Order created",
                    reference_id=order_id
                )
            )

        # Calculate delivery fee based on order value and distance
        delivery_fee = 0.0
        distance_km = 0.0

        if fulfillment_type == FulfillmentType.DELIVERY and delivery_address:
            # Get store location for distance calculation
            store = await self.db.stores.find_one({"store_id": store_id})
            if store and delivery_address.get("coordinates"):
                store_coords = store.get("address", {}).get("coordinates", {})
                if store_coords.get("type") == "Point":
                    store_lng, store_lat = store_coords.get("coordinates", [0, 0])
                    user_lat = delivery_address["coordinates"].get("lat", 0)
                    user_lng = delivery_address["coordinates"].get("lng", 0)

                    # Calculate haversine distance
                    import math
                    R = 6371  # Earth's radius in km
                    lat1_rad = math.radians(store_lat)
                    lat2_rad = math.radians(user_lat)
                    delta_lat = math.radians(user_lat - store_lat)
                    delta_lng = math.radians(user_lng - store_lng)
                    a = (math.sin(delta_lat / 2) ** 2 +
                         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng / 2) ** 2)
                    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                    distance_km = R * c

            # Apply minimum distance
            if distance_km < 0.8:
                distance_km = 0.8

            # Calculate delivery fee using the nukkad formula
            delivery_fee = self._calculate_delivery_fee(subtotal, distance_km)

        tax = subtotal * 0.05  # 5% GST
        total = subtotal - applied_discount + delivery_fee + tax

        pricing = {
            "subtotal": round(subtotal, 2),
            "discount": round(applied_discount, 2),
            "delivery_fee": round(delivery_fee, 2),
            "tax": round(tax, 2),
            "total": round(total, 2)
        }

        # Calculate estimated time based on fulfillment type and store settings
        store = await self.db.stores.find_one({"store_id": store_id})
        store_settings = store.get("settings", {}) if store else {}

        # Handle both flat and nested settings structure
        prep_time = (
            store_settings.get("preparation_time_minutes") or
            store_settings.get("takeaway", {}).get("preparation_time_minutes") or
            15
        )

        if fulfillment_type == FulfillmentType.TAKEAWAY:
            # Base preparation time for takeaway
            estimated_time = prep_time
        else:
            # Delivery: preparation + travel time (approx 3 mins per km)
            travel_time = int(distance_km * 3) if distance_km > 0 else 10
            estimated_time = prep_time + travel_time

        # Create order document
        order = {
            "order_id": order_id,
            "user_id": user_id,
            "store_id": store_id,
            "items": validated_items,
            "pricing": pricing,
            "total_amount": round(total, 2),  # Add total_amount for consistency
            "fulfillment_type": fulfillment_type,
            "delivery_address": delivery_address,
            "distance_km": round(distance_km, 2) if distance_km > 0 else None,
            "estimated_time": estimated_time,  # Estimated time in minutes
            "payment_method": payment_method or "PENDING",
            "status": OrderStatus.CREATED,
            "status_history": [
                {"status": OrderStatus.CREATED, "timestamp": now.isoformat(), "notes": None}
            ],
            "accepted_at": None,  # Will be set when store accepts
            "rider_id": None,
            "tracking_id": None,
            "session_id": session_id,
            "created_at": now,
            "updated_at": now
        }

        # Save to database
        await self.orders.insert_one(order)

        # Update user's total purchases (upsert for demo users)
        await self.db.users.update_one(
            {"user_id": user_id},
            {
                "$inc": {
                    "total_purchases": round(total, 2),
                    "total_orders": 1
                },
                "$set": {
                    "updated_at": now
                },
                "$setOnInsert": {
                    "user_id": user_id,
                    "name": "Demo User" if user_id == "DEMO_USER" else "User",
                    "phone": "0000000000" if user_id == "DEMO_USER" else "",
                    "created_at": now
                }
            },
            upsert=True
        )

        # Store in Redis for real-time access
        await self._cache_order_state(order)

        # Broadcast via WebSocket
        await ws_manager.broadcast_order_update(order)

        logger.info(f"Order {order_id} created for user {user_id} at store {store_id}")

        return order

    async def get_order(self, order_id: str) -> Optional[Dict]:
        """Get order by ID with customer name."""
        order = await self.orders.find_one({"order_id": order_id})
        if order and order.get("user_id"):
            user = await self.db.users.find_one({"user_id": order["user_id"]})
            if user:
                order["customer_name"] = user.get("name", "Customer")
        return order

    async def update_status(
        self,
        order_id: str,
        new_status: OrderStatus,
        notes: Optional[str] = None,
        rider_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update order status.

        - Validates status transition
        - Updates database and Redis
        - Triggers WebSocket notification
        """
        order = await self.orders.find_one({"order_id": order_id})
        if not order:
            raise ValueError("Order not found")

        current_status = OrderStatus(order["status"])

        # Validate transition
        if new_status not in STATUS_TRANSITIONS.get(current_status, []):
            raise ValueError(f"Invalid status transition from {current_status} to {new_status}")

        now = datetime.utcnow()

        # Prepare update
        update_data = {
            "status": new_status,
            "updated_at": now
        }

        if rider_id:
            update_data["rider_id"] = rider_id

        # Set accepted_at when order is confirmed
        if new_status == OrderStatus.CONFIRMED:
            update_data["accepted_at"] = now

        # Add to status history
        history_entry = {
            "status": new_status,
            "timestamp": now.isoformat(),
            "notes": notes
        }

        # Handle cancellation - release reserved stock
        if new_status == OrderStatus.CANCELLED:
            for item in order["items"]:
                await self.inventory_service.update_stock(
                    item["product_id"],
                    StockUpdate(
                        quantity=item["quantity"],
                        operation=StockOperation.RELEASE,
                        reason="Order cancelled",
                        reference_id=order_id
                    )
                )

        # Handle completion - finalize stock deduction
        if new_status in [OrderStatus.DELIVERED, OrderStatus.PICKED_UP]:
            # Stock was already reserved, no need to deduct again
            pass

        # Update database
        await self.orders.update_one(
            {"order_id": order_id},
            {
                "$set": update_data,
                "$push": {"status_history": history_entry}
            }
        )

        # Update order object for broadcast
        order["status"] = new_status
        order["updated_at"] = now
        if rider_id:
            order["rider_id"] = rider_id

        # Update Redis cache
        await self._cache_order_state(order)

        # Broadcast via WebSocket
        await ws_manager.broadcast_order_update(order)

        logger.info(f"Order {order_id} status updated: {current_status} -> {new_status}")

        return {
            "order_id": order_id,
            "previous_status": current_status,
            "current_status": new_status,
            "updated_at": now
        }

    async def get_user_orders(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Get order history for a user."""
        cursor = self.orders.find(
            {"user_id": user_id}
        ).sort("created_at", -1).skip(offset).limit(limit)

        orders = await cursor.to_list(length=limit)
        total = await self.orders.count_documents({"user_id": user_id})

        return {
            "user_id": user_id,
            "orders": orders,
            "total": total,
            "limit": limit,
            "offset": offset
        }

    async def get_store_orders(
        self,
        store_id: str,
        status: Optional[OrderStatus] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """Get orders for a store with customer names."""
        query = {"store_id": store_id}
        if status:
            query["status"] = status

        cursor = self.orders.find(query).sort("created_at", -1).limit(limit)
        orders = await cursor.to_list(length=limit)
        total = await self.orders.count_documents(query)

        # Enrich orders with customer names
        user_ids = list(set(order.get("user_id") for order in orders if order.get("user_id")))
        users = {}
        if user_ids:
            user_cursor = self.db.users.find({"user_id": {"$in": user_ids}})
            user_list = await user_cursor.to_list(length=len(user_ids))
            users = {user["user_id"]: user.get("name", "Customer") for user in user_list}
        
        # Add customer names to orders
        for order in orders:
            user_id = order.get("user_id")
            order["customer_name"] = users.get(user_id, "Customer")

        return {
            "store_id": store_id,
            "orders": orders,
            "total": total
        }

    async def get_active_orders(self, store_id: str) -> List[Dict]:
        """Get active (non-completed) orders for a store."""
        active_statuses = [
            OrderStatus.CREATED,
            OrderStatus.CONFIRMED,
            OrderStatus.PREPARING,
            OrderStatus.READY,
            OrderStatus.OUT_FOR_DELIVERY
        ]

        cursor = self.orders.find({
            "store_id": store_id,
            "status": {"$in": [s.value for s in active_statuses]}
        }).sort("created_at", -1)

        return await cursor.to_list(length=100)

    async def assign_rider(
        self,
        order_id: str,
        rider_id: str,
        tracking_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Assign a delivery rider to an order."""
        order = await self.orders.find_one({"order_id": order_id})
        if not order:
            raise ValueError("Order not found")

        if order["fulfillment_type"] != FulfillmentType.DELIVERY:
            raise ValueError("Cannot assign rider to takeaway order")

        now = datetime.utcnow()

        await self.orders.update_one(
            {"order_id": order_id},
            {
                "$set": {
                    "rider_id": rider_id,
                    "tracking_id": tracking_id,
                    "updated_at": now
                }
            }
        )

        order["rider_id"] = rider_id
        order["tracking_id"] = tracking_id
        order["updated_at"] = now

        # Notify rider via WebSocket
        await ws_manager.send_to_rider(rider_id, {
            "type": "new_delivery",
            "order_id": order_id,
            "store_id": order["store_id"],
            "delivery_address": order.get("delivery_address")
        })

        return {
            "order_id": order_id,
            "rider_id": rider_id,
            "tracking_id": tracking_id
        }

    async def _cache_order_state(self, order: Dict):
        """Cache order state in Redis for real-time access."""
        try:
            await RedisClient.set_order_state(order["order_id"], {
                "status": order["status"],
                "store_id": order["store_id"],
                "user_id": order["user_id"],
                "items": order["items"],
                "fulfillment_type": order["fulfillment_type"],
                "created_at": order["created_at"].isoformat() if isinstance(order["created_at"], datetime) else order["created_at"]
            })
        except Exception as e:
            logger.warning(f"Failed to cache order state: {e}")
