"""
Payments Router
Handles Razorpay payment integration
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import hmac
import hashlib

from app.db.mongodb import get_database
from app.config import settings

router = APIRouter(prefix="/payments", tags=["Payments"])


# ==================== Request/Response Models ====================

class CreateOrderRequest(BaseModel):
    amount: float  # In INR
    order_id: str
    store_id: str
    user_id: str
    notes: Optional[dict] = None


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    order_id: str


# ==================== Helper Functions ====================

def verify_razorpay_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """Verify Razorpay payment signature"""
    if not settings.RAZORPAY_KEY_SECRET:
        return False

    message = f"{order_id}|{payment_id}"
    expected_signature = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature)


# ==================== API Endpoints ====================

@router.get("/config")
async def get_payment_config():
    """Get Razorpay configuration for frontend"""
    return {
        "razorpay_key_id": settings.RAZORPAY_KEY_ID,
        "currency": "INR"
    }


@router.post("/create-order")
async def create_razorpay_order(request: CreateOrderRequest):
    """Create a Razorpay order for payment"""
    from app.config import settings
    
    # Check if Razorpay is bypassed for development
    if settings.BYPASS_RAZORPAY:
        # Return mock order for development
        return {
            "razorpay_order_id": f"order_dev_{request.order_id}",
            "amount": int(request.amount * 100),
            "currency": "INR",
            "key_id": "rzp_dev_bypass",
            "bypass": True
        }
    
    import httpx

    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        raise HTTPException(status_code=500, detail="Payment gateway not configured")

    # Amount in paise (Razorpay requires amount in smallest currency unit)
    amount_paise = int(request.amount * 100)

    razorpay_data = {
        "amount": amount_paise,
        "currency": "INR",
        "receipt": request.order_id,
        "notes": {
            "store_id": request.store_id,
            "user_id": request.user_id,
            "nukkadmart_order_id": request.order_id,
            **(request.notes or {})
        }
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.razorpay.com/v1/orders",
            json=razorpay_data,
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        )

        if response.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to create payment order")

        razorpay_order = response.json()

    # Save payment order to database
    db = await get_database()
    await db.payment_orders.insert_one({
        "razorpay_order_id": razorpay_order["id"],
        "nukkadmart_order_id": request.order_id,
        "store_id": request.store_id,
        "user_id": request.user_id,
        "amount": request.amount,
        "amount_paise": amount_paise,
        "currency": "INR",
        "status": "created",
        "created_at": datetime.utcnow()
    })

    return {
        "razorpay_order_id": razorpay_order["id"],
        "amount": amount_paise,
        "currency": "INR",
        "key_id": settings.RAZORPAY_KEY_ID
    }


@router.post("/verify")
async def verify_payment(request: VerifyPaymentRequest):
    """Verify Razorpay payment signature and update order status"""
    from app.config import settings
    
    # Check if Razorpay is bypassed for development
    if settings.BYPASS_RAZORPAY or request.razorpay_order_id.startswith("order_dev_"):
        # Auto-approve for development
        db = await get_database()
        
        # Update main order status
        await db.orders.update_one(
            {"order_id": request.order_id},
            {
                "$set": {
                    "payment_status": "PAID",
                    "payment_method": "RAZORPAY_DEV",
                    "razorpay_payment_id": f"pay_dev_{request.order_id}",
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        return {
            "success": True,
            "message": "Payment verified (development mode)",
            "order_id": request.order_id,
            "payment_id": f"pay_dev_{request.order_id}",
            "bypass": True
        }

    # Verify signature
    is_valid = verify_razorpay_signature(
        request.razorpay_order_id,
        request.razorpay_payment_id,
        request.razorpay_signature
    )

    if not is_valid:
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    db = await get_database()

    # Update payment order status
    await db.payment_orders.update_one(
        {"razorpay_order_id": request.razorpay_order_id},
        {
            "$set": {
                "razorpay_payment_id": request.razorpay_payment_id,
                "razorpay_signature": request.razorpay_signature,
                "status": "paid",
                "paid_at": datetime.utcnow()
            }
        }
    )

    # Update main order status
    await db.orders.update_one(
        {"order_id": request.order_id},
        {
            "$set": {
                "payment_status": "PAID",
                "payment_method": "RAZORPAY",
                "razorpay_payment_id": request.razorpay_payment_id,
                "updated_at": datetime.utcnow()
            }
        }
    )

    return {
        "success": True,
        "message": "Payment verified successfully",
        "order_id": request.order_id,
        "payment_id": request.razorpay_payment_id
    }


@router.post("/webhook")
async def razorpay_webhook(request: Request):
    """Handle Razorpay webhooks"""
    import json

    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature")

    if not signature or not settings.RAZORPAY_KEY_SECRET:
        raise HTTPException(status_code=400, detail="Invalid webhook")

    # Verify webhook signature
    expected_signature = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    payload = json.loads(body)
    event = payload.get("event")

    db = await get_database()

    if event == "payment.captured":
        payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        razorpay_order_id = payment_entity.get("order_id")

        await db.payment_orders.update_one(
            {"razorpay_order_id": razorpay_order_id},
            {
                "$set": {
                    "status": "captured",
                    "captured_at": datetime.utcnow()
                }
            }
        )

    elif event == "payment.failed":
        payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        razorpay_order_id = payment_entity.get("order_id")

        await db.payment_orders.update_one(
            {"razorpay_order_id": razorpay_order_id},
            {
                "$set": {
                    "status": "failed",
                    "failed_at": datetime.utcnow(),
                    "failure_reason": payment_entity.get("error_description")
                }
            }
        )

    return {"status": "ok"}


@router.get("/order/{order_id}/status")
async def get_payment_status(order_id: str):
    """Get payment status for an order"""
    db = await get_database()

    payment = await db.payment_orders.find_one({"nukkadmart_order_id": order_id})

    if not payment:
        return {"status": "not_found", "paid": False}

    return {
        "status": payment.get("status"),
        "paid": payment.get("status") in ["paid", "captured"],
        "razorpay_order_id": payment.get("razorpay_order_id"),
        "razorpay_payment_id": payment.get("razorpay_payment_id"),
        "amount": payment.get("amount")
    }
