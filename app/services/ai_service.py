"""
AI Service
Integration with Groq for OCR and AI-powered features
Fallback to Amazon Bedrock when AWS credits are available
"""
import json
import base64
import logging
import httpx
from typing import Optional, List, Dict, Any

from app.config import settings

logger = logging.getLogger(__name__)


class AIService:
    """Service for AI interactions using Groq (primary) or Bedrock (fallback)"""

    def __init__(self):
        self.groq_client = None
        self.groq_api_key = settings.GROQ_API_KEY
        self._initialize_client()

    def _initialize_client(self):
        """Initialize Groq client"""
        if self.groq_api_key:
            logger.info("Groq API key found, using Groq for AI services")
        else:
            logger.warning("No Groq API key found. Using mock responses.")

    def is_available(self) -> bool:
        """Check if AI service is available"""
        return bool(self.groq_api_key)

    # ==================== OCR with Groq Vision ====================

    async def extract_shopping_list(
        self,
        image_data: bytes,
        image_format: str = "jpeg"
    ) -> Dict[str, Any]:
        """
        Extract shopping list items from handwritten note image using Groq Vision.

        Args:
            image_data: Raw image bytes
            image_format: Image format (jpeg, png, webp)

        Returns:
            Dictionary with extracted items and raw text
        """
        if not self.is_available():
            logger.info("AI service not available, using mock OCR response")
            return self._mock_ocr_response()

        try:
            # Encode image to base64
            image_base64 = base64.b64encode(image_data).decode("utf-8")

            # Determine media type
            media_type = f"image/{image_format}"
            if image_format == "jpg":
                media_type = "image/jpeg"

            # Prepare the prompt for Groq Vision
            prompt = """You are an OCR assistant specialized in reading product lists and price tags.

Analyze this image and extract all products with their details.

For each product, identify:
1. Product name (full name including brand if visible)
2. Quantity/Size (e.g., 500ml, 1kg, 200g)
3. Price (in rupees)

Return your response in this exact format (plain text, one product per line):
Product Name (quantity) - ₹price

Example:
Full Cream Milk (500ml) - ₹33
Toned Milk (500ml) - ₹27
Amul Butter (100g) - ₹58

Important:
- Include the quantity in parentheses if visible
- Use ₹ symbol before price
- One product per line
- If price is not visible, skip that product
- Convert regional language names to English
- Be precise with quantities (ml, L, g, kg)

Return ONLY the product list, no other text or explanations."""

            # Call Groq Vision API
            async with httpx.AsyncClient(timeout=60.0) as client:
                payload = {
                    "model": settings.GROQ_VISION_MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{media_type};base64,{image_base64}"
                                    }
                                },
                                {
                                    "type": "text",
                                    "text": prompt
                                }
                            ]
                        }
                    ],
                    "max_tokens": 1024,
                    "temperature": 0.1
                }
                
                logger.info(f"Calling Groq Vision API with model: {settings.GROQ_VISION_MODEL}")
                
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.groq_api_key}",
                        "Content-Type": "application/json"
                    },
                    json=payload
                )

                if response.status_code != 200:
                    error_text = response.text
                    logger.error(f"Groq API error {response.status_code}: {error_text}")
                    return {
                        "success": False,
                        "raw_text": "",
                        "error": f"Groq API error {response.status_code}: {error_text}"
                    }

                result = response.json()

                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")

                if not content:
                    logger.warning("Groq returned empty content")
                    return {
                        "success": False,
                        "raw_text": "",
                        "error": "No text extracted from image"
                    }

                logger.info(f"Successfully extracted text: {content[:100]}...")

                # Parse the text into structured items
                items = self._parse_shopping_list_text(content)

                # Return the extracted text and parsed items
                return {
                    "success": True,
                    "raw_text": content.strip(),
                    "items": items,
                    "confidence": 0.85
                }

        except Exception as e:
            logger.error(f"Groq OCR error: {e}")
            return {
                "success": False,
                "raw_text": "",
                "error": str(e)
            }

    def _parse_shopping_list_text(self, text: str) -> List[Dict[str, Any]]:
        """
        Parse shopping list text into structured items.
        
        Expected format: Product Name (quantity) - ₹price
        Example: Full Cream Milk (500ml) - ₹33
        """
        import re
        
        items = []
        lines = text.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Pattern: Product Name (quantity) - ₹price
            # or: Product Name - ₹price
            pattern = r'^(.+?)\s*(?:\(([^)]+)\))?\s*-\s*₹?(\d+(?:\.\d+)?)'
            match = re.match(pattern, line)
            
            if match:
                name = match.group(1).strip()
                quantity_str = match.group(2)
                price = float(match.group(3))
                
                # Parse quantity and unit
                quantity = 1
                unit = "piece"
                
                if quantity_str:
                    # Extract number and unit from quantity string
                    qty_pattern = r'(\d+(?:\.\d+)?)\s*([a-zA-Z]+)'
                    qty_match = re.match(qty_pattern, quantity_str)
                    if qty_match:
                        quantity = float(qty_match.group(1))
                        unit = qty_match.group(2).lower()
                
                items.append({
                    "name": name,
                    "quantity": quantity,
                    "unit": unit,
                    "price": price,
                    "confidence": 0.85
                })
        
        return items

    # ==================== Nudge Engine with Groq ====================

    async def generate_nudge_recommendation(
        self,
        cart_items: List[Dict],
        user_behavior: Dict,
        slow_moving_products: List[Dict],
        store_settings: Dict
    ) -> Dict[str, Any]:
        """
        Generate personalized nudge recommendation using Groq.

        Args:
            cart_items: Current items in user's cart
            user_behavior: User behavior data (time on page, modifications, etc.)
            slow_moving_products: Products with low sales velocity
            store_settings: Store's discount settings

        Returns:
            Nudge recommendation with discount and messaging
        """
        if not self.is_available():
            logger.info("AI service not available, using mock nudge response")
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

Be strategic - don't offer discounts if abandonment probability is low.
Return ONLY valid JSON, no other text."""

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.groq_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": settings.GROQ_TEXT_MODEL,
                        "messages": [
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        "max_tokens": 512,
                        "temperature": 0.3
                    }
                )

                response.raise_for_status()
                result = response.json()

                content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")

                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    import re
                    json_match = re.search(r'\{[\s\S]*\}', content)
                    if json_match:
                        return json.loads(json_match.group())
                    else:
                        return self._mock_nudge_response(user_behavior)

        except Exception as e:
            logger.error(f"Groq nudge error: {e}")
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
        Forecast product demand using Groq.

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
}}

Return ONLY valid JSON, no other text."""

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.groq_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": settings.GROQ_TEXT_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 512,
                        "temperature": 0.2
                    }
                )

                response.raise_for_status()
                result = response.json()

                content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                return json.loads(content)

        except Exception as e:
            logger.error(f"Groq forecast error: {e}")
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
            "notes": "Mock response - AI service not configured",
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
ai_service = AIService()


def get_ai_service() -> AIService:
    """Get AI service instance"""
    return ai_service


# Backward compatibility aliases
bedrock_service = ai_service
get_bedrock_service = get_ai_service
