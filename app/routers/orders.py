"""
Order Service Router
Handles order creation, management, and real-time WebSocket updates
"""
from fastapi import APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect, Query
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
import json

from app.db.mongodb import get_database
from app.services.order_service import (
    OrderService,
    OrderStatus,
    FulfillmentType,
    ws_manager
)

router = APIRouter(prefix="/orders", tags=["Orders"])


# ==================== Request/Response Models ====================

class OrderItem(BaseModel):
    """Individual item in an order"""
    product_id: str
    name: Optional[str] = None
    quantity: int = Field(..., gt=0)
    unit_price: Optional[float] = Field(None, gt=0)
    subtotal: Optional[float] = None


class DeliveryAddress(BaseModel):
    """Delivery address details"""
    street: str
    landmark: Optional[str] = None
    city: str
    state: Optional[str] = None
    pincode: str
    coordinates: Optional[dict] = None
    phone: Optional[str] = None


class CreateOrderRequest(BaseModel):
    """Request to create a new order"""
    user_id: str
    store_id: str
    items: List[OrderItem]
    fulfillment_type: FulfillmentType
    delivery_address: Optional[DeliveryAddress] = None
    applied_discount: float = Field(default=0, ge=0)
    session_id: Optional[str] = None
    payment_method: Optional[str] = None


class OrderPricing(BaseModel):
    """Order pricing breakdown"""
    subtotal: float
    discount: float = 0
    delivery_fee: float = 0
    tax: float = 0
    total: float


class OrderResponse(BaseModel):
    """Full order response"""
    order_id: str
    user_id: str
    store_id: str
    items: List[dict]
    pricing: OrderPricing
    total_amount: Optional[float] = None
    fulfillment_type: str
    delivery_address: Optional[dict] = None
    distance_km: Optional[float] = None
    estimated_time: Optional[int] = None  # Estimated time in minutes
    accepted_at: Optional[datetime] = None
    payment_method: Optional[str] = None
    status: str
    status_history: List[dict]
    rider_id: Optional[str] = None
    tracking_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class UpdateStatusRequest(BaseModel):
    """Request to update order status"""
    status: OrderStatus
    notes: Optional[str] = None
    rider_id: Optional[str] = None


class AssignRiderRequest(BaseModel):
    """Request to assign delivery rider"""
    rider_id: str
    tracking_id: Optional[str] = None


# ==================== Dependencies ====================

async def get_order_service():
    """Get order service instance"""
    db = await get_database()
    return OrderService(db)


# ==================== API Endpoints ====================

@router.post("", response_model=OrderResponse, status_code=201)
async def create_order(
    request: CreateOrderRequest,
    service: OrderService = Depends(get_order_service)
):
    """
    Create a new order.

    **Process:**
    1. Validates all cart items exist and have sufficient stock
    2. Reserves stock for each item
    3. Calculates pricing (subtotal, tax, delivery fee, discount)
    4. Creates order in database
    5. Caches in Redis for real-time access
    6. Broadcasts to WebSocket subscribers

    **Pricing calculation:**
    - Subtotal: Sum of (quantity * unit_price) for all items
    - Tax: 5% GST on subtotal
    - Delivery fee: Rs. 30 for delivery orders, Rs. 0 for takeaway
    - Total: subtotal - discount + delivery_fee + tax

    **Example:**
    ```python
    response = requests.post("/api/v1/orders", json={
        "user_id": "USER_456",
        "store_id": "STORE_123",
        "items": [
            {"product_id": "PROD_001", "quantity": 2},
            {"product_id": "PROD_002", "quantity": 1}
        ],
        "fulfillment_type": "DELIVERY",
        "delivery_address": {
            "street": "123 Main St",
            "city": "Bangalore",
            "pincode": "560001"
        },
        "applied_discount": 45.00,
        "session_id": "sess_abc123"
    })
    ```
    """
    try:
        order = await service.create_order(
            user_id=request.user_id,
            store_id=request.store_id,
            items=[item.model_dump() for item in request.items],
            fulfillment_type=request.fulfillment_type,
            delivery_address=request.delivery_address.model_dump() if request.delivery_address else None,
            applied_discount=request.applied_discount,
            session_id=request.session_id,
            payment_method=request.payment_method
        )

        return OrderResponse(
            order_id=order["order_id"],
            user_id=order["user_id"],
            store_id=order["store_id"],
            items=order["items"],
            pricing=OrderPricing(**order["pricing"]),
            total_amount=order.get("total_amount"),
            fulfillment_type=order["fulfillment_type"],
            delivery_address=order.get("delivery_address"),
            distance_km=order.get("distance_km"),
            estimated_time=order.get("estimated_time"),
            accepted_at=order.get("accepted_at"),
            payment_method=order.get("payment_method"),
            status=order["status"],
            status_history=order["status_history"],
            rider_id=order.get("rider_id"),
            tracking_id=order.get("tracking_id"),
            created_at=order["created_at"],
            updated_at=order["updated_at"]
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str,
    service: OrderService = Depends(get_order_service)
):
    """Get order details by ID."""
    order = await service.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return OrderResponse(
        order_id=order["order_id"],
        user_id=order["user_id"],
        store_id=order["store_id"],
        items=order["items"],
        pricing=OrderPricing(**order["pricing"]),
        total_amount=order.get("total_amount"),
        fulfillment_type=order["fulfillment_type"],
        delivery_address=order.get("delivery_address"),
        distance_km=order.get("distance_km"),
        estimated_time=order.get("estimated_time"),
        accepted_at=order.get("accepted_at"),
        payment_method=order.get("payment_method"),
        status=order["status"],
        status_history=order["status_history"],
        rider_id=order.get("rider_id"),
        tracking_id=order.get("tracking_id"),
        created_at=order["created_at"],
        updated_at=order["updated_at"]
    )


@router.put("/{order_id}/status")
async def update_order_status(
    order_id: str,
    request: UpdateStatusRequest,
    service: OrderService = Depends(get_order_service)
):
    """
    Update order status.

    **Status flow:**
    ```
    CREATED → CONFIRMED → PREPARING → READY →
      ├─→ PICKED_UP (Takeaway)
      └─→ OUT_FOR_DELIVERY → DELIVERED (Delivery)

    Any status can transition to CANCELLED (except completed orders)
    ```

    **WebSocket notifications:**
    - Customer receives status update
    - Store receives status update
    - Rider receives status update (if assigned)

    **Stock management:**
    - On CANCELLED: Reserved stock is released
    - On DELIVERED/PICKED_UP: Stock deduction is finalized
    """
    try:
        result = await service.update_status(
            order_id=order_id,
            new_status=request.status,
            notes=request.notes,
            rider_id=request.rider_id
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{order_id}/assign-rider")
async def assign_rider(
    order_id: str,
    request: AssignRiderRequest,
    service: OrderService = Depends(get_order_service)
):
    """
    Assign a delivery rider to an order.

    Only applicable for DELIVERY orders.
    Notifies the rider via WebSocket.
    """
    try:
        result = await service.assign_rider(
            order_id=order_id,
            rider_id=request.rider_id,
            tracking_id=request.tracking_id
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/user/{user_id}")
async def get_user_orders(
    user_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: OrderService = Depends(get_order_service)
):
    """Get order history for a user."""
    result = await service.get_user_orders(user_id, limit, offset)
    return result


@router.get("")
async def get_orders_by_query(
    user_id: Optional[str] = Query(None),
    store_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: OrderService = Depends(get_order_service)
):
    """Get orders by user_id or store_id query parameter."""
    if user_id:
        result = await service.get_user_orders(user_id, limit, offset)
        
        # Enrich orders with store names
        db = await get_database()
        for order in result["orders"]:
            # Remove MongoDB _id field (not JSON serializable)
            if "_id" in order:
                del order["_id"]

            # Convert datetime objects to ISO strings for JSON serialization
            if isinstance(order.get("created_at"), datetime):
                order["created_at"] = order["created_at"].isoformat()
            if isinstance(order.get("updated_at"), datetime):
                order["updated_at"] = order["updated_at"].isoformat()
            if isinstance(order.get("accepted_at"), datetime):
                order["accepted_at"] = order["accepted_at"].isoformat()

            # Convert status_history timestamps
            if "status_history" in order:
                for status_entry in order["status_history"]:
                    if isinstance(status_entry.get("timestamp"), datetime):
                        status_entry["timestamp"] = status_entry["timestamp"].isoformat()

            # Convert enum values to strings if needed
            if hasattr(order.get("status"), "value"):
                order["status"] = order["status"].value
            if hasattr(order.get("fulfillment_type"), "value"):
                order["fulfillment_type"] = order["fulfillment_type"].value

            # Add store name
            store = await db.stores.find_one({"store_id": order["store_id"]})
            if store:
                order["store_name"] = store.get("name", "Unknown Store")
            else:
                order["store_name"] = "Unknown Store"
        
        return result
    elif store_id:
        result = await service.get_store_orders(store_id, limit, offset)
        return result
    else:
        raise HTTPException(status_code=400, detail="Either user_id or store_id is required")


@router.get("/store/{store_id}")
async def get_store_orders(
    store_id: str,
    status: Optional[OrderStatus] = None,
    limit: int = Query(50, ge=1, le=200),
    service: OrderService = Depends(get_order_service)
):
    """Get orders for a store, optionally filtered by status."""
    result = await service.get_store_orders(store_id, status, limit)
    return result


@router.get("/store/{store_id}/active")
async def get_active_orders(
    store_id: str,
    service: OrderService = Depends(get_order_service)
):
    """Get active (non-completed) orders for a store."""
    orders = await service.get_active_orders(store_id)
    return {
        "store_id": store_id,
        "active_orders": orders,
        "count": len(orders)
    }


# ==================== WebSocket Endpoints ====================

@router.websocket("/ws/customer/{user_id}")
async def customer_websocket(websocket: WebSocket, user_id: str):
    """
    WebSocket endpoint for customers to receive order updates.

    **Connection:**
    ```javascript
    const ws = new WebSocket('ws://localhost:8000/api/v1/orders/ws/customer/USER_456');

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'order_update') {
            console.log(`Order ${data.order_id} is now ${data.status}`);
        }
    };
    ```

    **Messages received:**
    - `order_update`: Status change notification
    - `ack`: Acknowledgment of sent message
    """
    await ws_manager.connect(websocket, "customers", user_id)
    try:
        while True:
            data = await websocket.receive_text()
            # Echo acknowledgment
            await websocket.send_json({"type": "ack", "received": data})
    except WebSocketDisconnect:
        ws_manager.disconnect("customers", user_id)


@router.websocket("/ws/store/{store_id}")
async def store_websocket(websocket: WebSocket, store_id: str):
    """
    WebSocket endpoint for shopkeepers to receive order notifications.

    **Connection:**
    ```javascript
    const ws = new WebSocket('ws://localhost:8000/api/v1/orders/ws/store/STORE_123');
    ```

    **Messages received:**
    - `order_update`: New order or status change
    - `new_order`: New order notification

    **Actions (send to server):**
    ```javascript
    // Accept an order
    ws.send(JSON.stringify({
        action: 'accept_order',
        order_id: 'ORD_20260214_ABC123'
    }));

    // Mark as ready
    ws.send(JSON.stringify({
        action: 'mark_ready',
        order_id: 'ORD_20260214_ABC123'
    }));
    ```
    """
    await ws_manager.connect(websocket, "stores", store_id)
    db = await get_database()
    service = OrderService(db)

    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                action = message.get("action")
                order_id = message.get("order_id")

                if action == "accept_order" and order_id:
                    await service.update_status(order_id, OrderStatus.CONFIRMED)
                    await websocket.send_json({"type": "action_result", "success": True, "action": "accept_order"})

                elif action == "start_preparing" and order_id:
                    await service.update_status(order_id, OrderStatus.PREPARING)
                    await websocket.send_json({"type": "action_result", "success": True, "action": "start_preparing"})

                elif action == "mark_ready" and order_id:
                    await service.update_status(order_id, OrderStatus.READY)
                    await websocket.send_json({"type": "action_result", "success": True, "action": "mark_ready"})

                elif action == "cancel_order" and order_id:
                    await service.update_status(order_id, OrderStatus.CANCELLED, notes=message.get("reason"))
                    await websocket.send_json({"type": "action_result", "success": True, "action": "cancel_order"})

                else:
                    await websocket.send_json({"type": "error", "message": "Unknown action"})

            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
            except Exception as e:
                await websocket.send_json({"type": "error", "message": str(e)})

    except WebSocketDisconnect:
        ws_manager.disconnect("stores", store_id)


@router.websocket("/ws/rider/{rider_id}")
async def rider_websocket(websocket: WebSocket, rider_id: str):
    """
    WebSocket endpoint for delivery riders.

    **Messages received:**
    - `new_delivery`: New delivery assignment
    - `order_update`: Order status change

    **Actions (send to server):**
    ```javascript
    // Mark pickup complete
    ws.send(JSON.stringify({
        action: 'pickup_complete',
        order_id: 'ORD_20260214_ABC123'
    }));

    // Mark as delivered
    ws.send(JSON.stringify({
        action: 'delivered',
        order_id: 'ORD_20260214_ABC123'
    }));

    // Update location
    ws.send(JSON.stringify({
        action: 'update_location',
        lat: 12.9716,
        lng: 77.5946
    }));
    ```
    """
    await ws_manager.connect(websocket, "riders", rider_id)
    db = await get_database()
    service = OrderService(db)

    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                action = message.get("action")
                order_id = message.get("order_id")

                if action == "pickup_complete" and order_id:
                    await service.update_status(order_id, OrderStatus.OUT_FOR_DELIVERY)
                    await websocket.send_json({"type": "action_result", "success": True, "action": "pickup_complete"})

                elif action == "delivered" and order_id:
                    await service.update_status(order_id, OrderStatus.DELIVERED)
                    await websocket.send_json({"type": "action_result", "success": True, "action": "delivered"})

                elif action == "update_location":
                    lat = message.get("lat")
                    lng = message.get("lng")
                    # Store location in Redis for real-time tracking
                    # Could broadcast to customer watching the delivery
                    await websocket.send_json({"type": "location_updated", "lat": lat, "lng": lng})

                else:
                    await websocket.send_json({"type": "error", "message": "Unknown action"})

            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
            except Exception as e:
                await websocket.send_json({"type": "error", "message": str(e)})

    except WebSocketDisconnect:
        ws_manager.disconnect("riders", rider_id)


# ==================== Delivery Fee Calculator ====================

class DeliveryFeeRequest(BaseModel):
    """Request to calculate delivery fee"""
    store_id: str
    order_value: float
    user_lat: float
    user_lng: float


class DeliveryFeeResponse(BaseModel):
    """Delivery fee calculation response"""
    delivery_fee: float
    distance_km: float
    estimated_time: int  # minutes
    free_delivery: bool
    free_delivery_threshold: float


@router.post("/calculate-delivery-fee", response_model=DeliveryFeeResponse)
async def calculate_delivery_fee(
    request: DeliveryFeeRequest,
    service: OrderService = Depends(get_order_service)
):
    """
    Calculate delivery fee based on order value and distance.

    Uses the nukkad formula which considers:
    - Distance from store to customer
    - Order value (higher orders get lower/free delivery)
    - Long distance surcharge for orders > 5km
    - Short value surcharge for orders < Rs 200
    """
    import math

    db = await get_database()
    store = await db.stores.find_one({"store_id": request.store_id})

    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    # Get store coordinates
    store_coords = store.get("address", {}).get("coordinates", {})
    if store_coords.get("type") == "Point":
        store_lng, store_lat = store_coords.get("coordinates", [0, 0])
    else:
        store_lat = store_coords.get("lat", 0)
        store_lng = store_coords.get("lng", 0)

    # Calculate haversine distance
    R = 6371  # Earth's radius in km
    lat1_rad = math.radians(store_lat)
    lat2_rad = math.radians(request.user_lat)
    delta_lat = math.radians(request.user_lat - store_lat)
    delta_lng = math.radians(request.user_lng - store_lng)
    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance_km = R * c

    # Calculate delivery fee using the service method
    delivery_fee = service._calculate_delivery_fee(request.order_value, distance_km)

    # Calculate estimated time (prep time + travel time)
    store_settings = store.get("settings", {})
    prep_time = store_settings.get("preparation_time_minutes", 15)
    travel_time = int(distance_km * 3) if distance_km > 0 else 10
    estimated_time = prep_time + travel_time

    # Check if free delivery applies (Rs 199 threshold)
    free_delivery = request.order_value >= 199

    return DeliveryFeeResponse(
        delivery_fee=round(delivery_fee, 2),
        distance_km=round(distance_km, 2),
        estimated_time=estimated_time,
        free_delivery=free_delivery,
        free_delivery_threshold=199.0
    )


# ==================== Order Status Info ====================

@router.get("/status-flow")
async def get_status_flow():
    """Get the order status flow diagram."""
    return {
        "statuses": [s.value for s in OrderStatus],
        "transitions": {
            "CREATED": ["CONFIRMED", "CANCELLED"],
            "CONFIRMED": ["PREPARING", "CANCELLED"],
            "PREPARING": ["READY", "CANCELLED"],
            "READY": ["PICKED_UP", "OUT_FOR_DELIVERY"],
            "OUT_FOR_DELIVERY": ["DELIVERED"],
            "PICKED_UP": [],
            "DELIVERED": [],
            "CANCELLED": []
        },
        "terminal_statuses": ["PICKED_UP", "DELIVERED", "CANCELLED"],
        "fulfillment_types": [f.value for f in FulfillmentType]
    }
