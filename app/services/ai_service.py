"""
AI Service
Integration with Groq for OCR and AI-powered features
Fallback to Amazon Bedrock when AWS credits are available
"""
import json
import base64
import logging
import httpx
import asyncio
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

        # Encode image to base64
        image_base64 = base64.b64encode(image_data).decode("utf-8")

        # Determine media type
        media_type = f"image/{image_format}"
        if image_format == "jpg":
            media_type = "image/jpeg"

        # Prepare the prompt for Groq Vision
        # Prepare the prompt for Groq Vision with strict JSON output
        prompt = """You are an expert AI assistant for an Indian grocery store (kirana shop). Your task is to extract product items from a handwritten shopping list image.

IMPORTANT: This is an Indian grocery shopping list. Common items include:
- Rice varieties: Basmati Rice, Regular Rice, Sona Masoori
- Beverages: Bisleri Water, Coca Cola, Pepsi, Tea, Coffee
- Staples: Atta (wheat flour), Maida, Sugar, Salt, Oil
- Pulses: Dal, Moong Dal, Toor Dal, Chana Dal
- Spices: Turmeric, Red Chili, Coriander
- Dairy: Milk, Paneer, Curd, Butter, Ghee
- Snacks: Biscuits, Namkeen, Chips

READ CAREFULLY - Common handwriting mistakes to avoid:
- "Basmati" should NOT be read as "Biscuit" or "Biskuit"
- "Bisleri" should NOT be read as "Biscuit" or "Biskuit"  
- "Rice" should NOT be confused with other words
- Pay attention to word length and letter shapes

Analyze the image and extract every item listed. For each item, return a JSON object with the following fields:

- `raw_text`: The exact text written for this item (e.g., "Basmati Rice", "Bisleri Water").
- `search_term_english`: The English translation of the product name for searching (e.g., "Basmati Rice", "Bisleri Water"). If unreadable, set to null.
- `req_qty`: The numeric quantity requested (e.g., 200, 1). If not specified, default to 1.
- `req_unit`: The unit of measurement (e.g., "gm", "kg", "ml", "L", "piece"). If not specified, default to "piece".
- `is_brand_specified`: Boolean, true if a specific brand is mentioned (e.g., "Bisleri", "India Gate").
- `confidence_score`: A number between 0 and 1 indicating how confident you are in reading this item.
- `is_unreadable`: Boolean, set to true if the text is illegible or confidence is low (< 0.5).

Return the result as a strictly valid JSON array of objects. Do not include any markdown formatting, code blocks, or explanations. Just the raw JSON array.

Example Output:
[
  {
    "raw_text": "Basmati Rice", 
    "search_term_english": "Basmati Rice",
    "req_qty": 1,
    "req_unit": "kg",
    "is_brand_specified": false,
    "confidence_score": 0.95,
    "is_unreadable": false
  },
  {
    "raw_text": "Bisleri Water", 
    "search_term_english": "Bisleri Water",
    "req_qty": 1,
    "req_unit": "L",
    "is_brand_specified": true,
    "confidence_score": 0.90,
    "is_unreadable": false
  }
]"""

        # Check if Bedrock is configured
        if not settings.AWS_REGION:
            logger.error("AWS_REGION not configured for Bedrock OCR")
            return {
                "success": False,
                "raw_text": "",
                "error": "AWS Bedrock not configured"
            }
                
        # Prepare image data for Bedrock
        import boto3
        try:
            # Use region from settings, fallback to ap-south-1
            region = settings.AWS_REGION or "ap-south-1"
            
            # Determine Nova Pro model - use India region for better latency
            model_id = "apac.amazon.nova-pro-v1:0"  # India region model
            if hasattr(settings, "BEDROCK_MODEL_ID") and getattr(settings, "BEDROCK_MODEL_ID"):
                model_id = getattr(settings, "BEDROCK_MODEL_ID")
            elif hasattr(settings, "BEDROCK_NOVA_PRO_MODEL_ID") and getattr(settings, "BEDROCK_NOVA_PRO_MODEL_ID"):
                model_id = getattr(settings, "BEDROCK_NOVA_PRO_MODEL_ID")
                
            client_kwargs = {"region_name": region}
            if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
                client_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
                client_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
            
            bedrock_client = boto3.client("bedrock-runtime", **client_kwargs)
            
            logger.info(f"Calling Bedrock Converse API for OCR with model: {model_id} in {region}")
            
            # Create the message for Converse API with strict JSON instructions
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "image": {
                                "format": image_format if image_format in ["png", "jpeg", "webp", "gif"] else "jpeg",
                                "source": {
                                    "bytes": image_data
                                }
                            }
                        },
                        {
                            "text": prompt
                        }
                    ]
                }
            ]
            
            # Call Nova Pro using Converse API in an async executor
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: bedrock_client.converse(
                    modelId=model_id,
                    messages=messages,
                    inferenceConfig={
                        "maxTokens": 2048,
                        "temperature": 0.0  # Set to 0 for deterministic OCR results
                    }
                )
            )
            
            # Extract text content from Converse response
            content = ""
            output_message = response.get("output", {}).get("message", {})
            for block in output_message.get("content", []):
                if "text" in block:
                    content += block["text"]
                    
            if not content:
                logger.warning("Bedrock returned empty content")
                return {
                    "success": False,
                    "raw_text": "",
                    "error": "No text extracted from image"
                }

            logger.info(f"Successfully extracted OCR text via Nova Pro: {content[:100]}...")

            # Parse the text into structured items
            try:
                # Clean up content if it contains markdown code blocks
                content = content.strip()
                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
                
                items = json.loads(content)
                
                # Validate items structure
                validated_items = []
                for item in items:
                    if isinstance(item, dict):
                        validated_items.append(item)
                        
                return {
                    "success": True,
                    "raw_text": json.dumps(validated_items, indent=2), # Store JSON representation as raw text for debugging
                    "items": validated_items,
                    "confidence": 0.95
                }
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON response from Nova Pro: {e}")
                import re
                # One last attempt to find a JSON array in the text
                json_match = re.search(r'\[[\s\S]*\]', content)
                if json_match:
                    try:
                        items = json.loads(json_match.group())
                        return {
                            "success": True,
                            "raw_text": json.dumps(items, indent=2),
                            "items": items,
                            "confidence": 0.90
                        }
                    except Exception:
                        pass
                        
                return {
                    "success": False,
                    "raw_text": content,
                    "error": "Failed to parse AI response",
                    "items": []
                }

        except Exception as e:
            logger.error(f"Bedrock OCR error: {e}")
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
        items = [
            {
                "raw_text": "2kg Rice",
                "search_term_english": "Rice",
                "req_qty": 2,
                "req_unit": "kg",
                "is_brand_specified": false,
                "confidence_score": 0.95,
                "is_unreadable": false
            },
            {
                "raw_text": "100g Colgate",
                "search_term_english": "Colgate Toothpaste",
                "req_qty": 100,
                "req_unit": "g",
                "is_brand_specified": true,
                "confidence_score": 0.90,
                "is_unreadable": false
            },
            {
                "raw_text": "scribble",
                "search_term_english": null,
                "req_qty": 1,
                "req_unit": "piece",
                "is_brand_specified": false,
                "confidence_score": 0.1,
                "is_unreadable": true
            }
        ]
        return {
            "items": items,
            "raw_text": json.dumps(items, indent=2),
            "language_detected": "Mixed",
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
