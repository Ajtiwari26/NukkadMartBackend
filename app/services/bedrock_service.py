"""
Amazon Bedrock Service
Integration with Amazon Nova for OCR and AI-powered features
"""
import boto3
import json
import base64
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from app.config import settings

logger = logging.getLogger(__name__)


class BedrockService:
    """Service for Amazon Bedrock / Nova AI interactions"""

    def __init__(self):
        self.client = None
        self.runtime_client = None
        self._initialize_clients()

    def _initialize_clients(self):
        """Initialize Bedrock clients"""
        try:
            session_kwargs = {
                "region_name": settings.AWS_REGION
            }

            # Use explicit credentials if provided
            if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
                session_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
                session_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY

            session = boto3.Session(**session_kwargs)

            self.runtime_client = session.client("bedrock-runtime")
            self.client = session.client("bedrock")

            logger.info("Bedrock clients initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize Bedrock clients: {e}. Using mock mode.")
            self.client = None
            self.runtime_client = None

    def is_available(self) -> bool:
        """Check if Bedrock is available"""
        return self.runtime_client is not None

    # ==================== OCR with Nova Multimodal ====================

    async def extract_shopping_list(
        self,
        image_data: bytes,
        image_format: str = "jpeg"
    ) -> Dict[str, Any]:
        """
        Extract shopping list items from handwritten note image using Amazon Nova.

        Args:
            image_data: Raw image bytes
            image_format: Image format (jpeg, png, webp)

        Returns:
            Dictionary with extracted items and raw text
        """
        if not self.is_available():
            logger.info("Bedrock not available, using mock OCR response")
            return self._mock_ocr_response()

        try:
            # Encode image to base64
            image_base64 = base64.b64encode(image_data).decode("utf-8")

            # Prepare the prompt for Nova
            prompt = """You are an OCR assistant specialized in reading handwritten shopping lists from Indian households.

Analyze this handwritten shopping list image and extract all items with their quantities.

For each item, identify:
1. Item name (in English, even if written in Hindi/regional language)
2. Quantity (numeric value)
3. Unit (kg, g, L, ml, pieces, packets, etc.)

Return your response in this exact JSON format:
{
    "items": [
        {"name": "Rice", "quantity": 2, "unit": "kg", "confidence": 0.95},
        {"name": "Dal", "quantity": 1, "unit": "kg", "confidence": 0.90}
    ],
    "raw_text": "The exact text you can read from the image",
    "language_detected": "Hindi/English/Mixed",
    "notes": "Any observations about unclear items"
}

Important:
- Convert regional names to common English names (e.g., "चावल" → "Rice", "दाल" → "Dal")
- Include a confidence score (0-1) for each item
- If quantity is unclear, make a reasonable assumption and note low confidence
- Common Indian units: kg, g, L, ml, pav (250g), adhha (500g), kilo
- Handle abbreviations: 1/2 kg = 0.5 kg, 1kg = 1 kg"""

            # Call Nova Multimodal
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": f"image/{image_format}",
                                    "data": image_base64
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ]
            }

            response = self.runtime_client.invoke_model(
                modelId=settings.BEDROCK_MODEL_ID,
                body=json.dumps(request_body),
                contentType="application/json",
                accept="application/json"
            )

            response_body = json.loads(response["body"].read())
            content = response_body.get("content", [{}])[0].get("text", "{}")

            # Parse the JSON response
            try:
                result = json.loads(content)
            except json.JSONDecodeError:
                # Try to extract JSON from the response
                import re
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    result = json.loads(json_match.group())
                else:
                    result = {"items": [], "raw_text": content, "error": "Failed to parse response"}

            return result

        except Exception as e:
            logger.error(f"Bedrock OCR error: {e}")
            return {
                "items": [],
                "raw_text": "",
                "error": str(e)
            }

    # ==================== Nudge Engine with Nova Act ====================

    async def generate_nudge_recommendation(
        self,
        cart_items: List[Dict],
        user_behavior: Dict,
        slow_moving_products: List[Dict],
        store_settings: Dict
    ) -> Dict[str, Any]:
        """
        Generate personalized nudge recommendation using Amazon Nova Act.

        Args:
            cart_items: Current items in user's cart
            user_behavior: User behavior data (time on page, modifications, etc.)
            slow_moving_products: Products with low sales velocity
            store_settings: Store's discount settings

        Returns:
            Nudge recommendation with discount and messaging
        """
        if not self.is_available():
            logger.info("Bedrock not available, using mock nudge response")
            return self._mock_nudge_response(user_behavior)

        try:
            prompt = f"""You are an AI negotiation agent for a local grocery store. Your goal is to prevent cart abandonment while maximizing conversion and clearing slow-moving inventory.

## Current Situation

**Cart Items:**
{json.dumps(cart_items, indent=2)}

**User Behavior Signals:**
- Time on cart page: {user_behavior.get('time_on_cart', 0)} seconds
- Cart modifications: {user_behavior.get('cart_modifications', 0)}
- Exit intent detected: {user_behavior.get('exit_intent', False)}
- Abandonment probability: {user_behavior.get('abandonment_score', 0) * 100:.1f}%

**Slow-Moving Products in Cart:**
{json.dumps(slow_moving_products, indent=2)}

**Store Settings:**
- Max discount allowed: {store_settings.get('max_discount_percent', 15)}%
- Min discount: {store_settings.get('min_discount_percent', 5)}%

## Your Task

Analyze the situation and recommend a personalized offer to convert this customer.

Consider:
1. Higher discount on slow-moving items (helps clear inventory)
2. Urgency messaging based on abandonment probability
3. Cart value optimization (suggest adding items for free delivery)

Return your recommendation in this exact JSON format:
{{
    "should_nudge": true,
    "nudge_type": "discount",
    "discount_percent": 10,
    "discount_on_products": ["PROD_001", "PROD_002"],
    "message": "Complete your order now and get 10% off!",
    "secondary_message": "Your discount expires in 5 minutes",
    "urgency_level": "high",
    "expires_in_seconds": 300,
    "reasoning": "Why this recommendation was made"
}}

Be strategic - don't offer discounts if abandonment probability is low."""

            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 512,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            }

            response = self.runtime_client.invoke_model(
                modelId=settings.BEDROCK_NOVA_ACT_MODEL_ID,
                body=json.dumps(request_body),
                contentType="application/json",
                accept="application/json"
            )

            response_body = json.loads(response["body"].read())
            content = response_body.get("content", [{}])[0].get("text", "{}")

            try:
                result = json.loads(content)
            except json.JSONDecodeError:
                import re
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    result = json.loads(json_match.group())
                else:
                    result = self._mock_nudge_response(user_behavior)

            return result

        except Exception as e:
            logger.error(f"Bedrock nudge error: {e}")
            return self._mock_nudge_response(user_behavior)

    # ==================== Demand Forecasting ====================

    async def forecast_demand(
        self,
        product_id: str,
        historical_sales: List[Dict],
        current_stock: int,
        seasonal_factors: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Forecast product demand using Nova.

        Args:
            product_id: Product identifier
            historical_sales: List of daily sales data
            current_stock: Current stock level
            seasonal_factors: Optional seasonal adjustment factors

        Returns:
            Demand forecast with recommended order quantity
        """
        if not self.is_available():
            return self._mock_forecast_response(historical_sales, current_stock)

        try:
            prompt = f"""You are a demand forecasting AI for a local grocery store.

**Product:** {product_id}

**Historical Sales (last 30 days):**
{json.dumps(historical_sales[-30:], indent=2)}

**Current Stock:** {current_stock} units

**Seasonal Factors:** {json.dumps(seasonal_factors or {}, indent=2)}

Analyze the sales pattern and forecast:
1. Predicted daily demand for next 7 days
2. Recommended reorder quantity
3. Safety stock level
4. Trend (increasing/stable/decreasing)

Return in JSON format:
{{
    "predicted_daily_demand": 15.5,
    "predicted_weekly_demand": 108,
    "trend": "stable",
    "confidence_score": 0.85,
    "recommended_order_quantity": 150,
    "safety_stock": 45,
    "reorder_point": 60,
    "reasoning": "Brief explanation"
}}"""

            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 512,
                "messages": [{"role": "user", "content": prompt}]
            }

            response = self.runtime_client.invoke_model(
                modelId=settings.BEDROCK_MODEL_ID,
                body=json.dumps(request_body),
                contentType="application/json",
                accept="application/json"
            )

            response_body = json.loads(response["body"].read())
            content = response_body.get("content", [{}])[0].get("text", "{}")

            return json.loads(content)

        except Exception as e:
            logger.error(f"Bedrock forecast error: {e}")
            return self._mock_forecast_response(historical_sales, current_stock)

    # ==================== Mock Responses ====================

    def _mock_ocr_response(self) -> Dict[str, Any]:
        """Mock OCR response for development/testing"""
        return {
            "items": [
                {"name": "Rice", "quantity": 2, "unit": "kg", "confidence": 0.95},
                {"name": "Toor Dal", "quantity": 1, "unit": "kg", "confidence": 0.92},
                {"name": "Sugar", "quantity": 500, "unit": "g", "confidence": 0.88},
                {"name": "Milk", "quantity": 2, "unit": "L", "confidence": 0.91},
                {"name": "Bread", "quantity": 1, "unit": "packet", "confidence": 0.85},
                {"name": "Cooking Oil", "quantity": 1, "unit": "L", "confidence": 0.89},
                {"name": "Salt", "quantity": 1, "unit": "kg", "confidence": 0.94},
            ],
            "raw_text": "2kg Rice\n1kg Dal\n500g Sugar\n2L Milk\n1 Bread\n1L Oil\n1kg Salt",
            "language_detected": "Mixed (Hindi/English)",
            "notes": "Mock response - Bedrock not configured",
            "is_mock": True
        }

    def _mock_nudge_response(self, user_behavior: Dict) -> Dict[str, Any]:
        """Mock nudge response for development/testing"""
        abandonment_score = user_behavior.get("abandonment_score", 0.7)

        if abandonment_score >= 0.9:
            discount = 12
            urgency = "high"
        elif abandonment_score >= 0.8:
            discount = 10
            urgency = "high"
        elif abandonment_score >= 0.7:
            discount = 7
            urgency = "medium"
        else:
            discount = 5
            urgency = "low"

        return {
            "should_nudge": abandonment_score >= 0.7,
            "nudge_type": "discount",
            "discount_percent": discount,
            "discount_on_products": [],
            "message": f"Complete your order now and get {discount}% off!",
            "secondary_message": "Limited time offer - expires soon!",
            "urgency_level": urgency,
            "expires_in_seconds": 300,
            "reasoning": f"Mock response - User shows {abandonment_score*100:.0f}% abandonment probability",
            "is_mock": True
        }

    def _mock_forecast_response(
        self,
        historical_sales: List[Dict],
        current_stock: int
    ) -> Dict[str, Any]:
        """Mock forecast response for development/testing"""
        # Simple average-based forecast
        if historical_sales:
            recent_sales = [s.get("quantity", 0) for s in historical_sales[-7:]]
            avg_daily = sum(recent_sales) / len(recent_sales) if recent_sales else 10
        else:
            avg_daily = 10

        weekly_demand = avg_daily * 7
        safety_stock = int(avg_daily * 3)  # 3 days safety stock
        reorder_qty = int(weekly_demand + safety_stock - current_stock)

        return {
            "predicted_daily_demand": round(avg_daily, 1),
            "predicted_weekly_demand": round(weekly_demand, 0),
            "trend": "stable",
            "confidence_score": 0.75,
            "recommended_order_quantity": max(0, reorder_qty),
            "safety_stock": safety_stock,
            "reorder_point": int(avg_daily * 3),
            "reasoning": "Mock response - Based on simple moving average",
            "is_mock": True
        }


# Singleton instance
bedrock_service = BedrockService()


def get_bedrock_service() -> BedrockService:
    """Get Bedrock service instance"""
    return bedrock_service
