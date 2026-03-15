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
        self._groq_key_valid = True  # Set to False after a 401 to skip Groq permanently
        self._initialize_client()

    def _initialize_client(self):
        """Initialize Groq client"""
        if self.groq_api_key:
            logger.info("Groq API key found, using Groq for AI services")
        else:
            logger.warning("No Groq API key found. Will use Bedrock directly.")

    def is_available(self) -> bool:
        """Check if Groq AI service is available and key is valid"""
        return bool(self.groq_api_key) and self._groq_key_valid

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
        prompt = """You are an expert OCR assistant for an Indian grocery store (kirana shop). Your task is to extract product items from a handwritten shopping list image.

CRITICAL: The shopping list may be written in HINDI (Devanagari script), ENGLISH, or a MIX of both. You MUST read and understand Hindi text perfectly.

HINDI READING INSTRUCTIONS:
- Read Devanagari script characters carefully and accurately
- Translate Hindi product names to English in the `search_term_english` field
- Do NOT mark Hindi text as unreadable just because it is in a different script
- Common Hindi grocery words: दूध=Milk, चावल=Rice, आटा=Flour/Atta, दाल=Lentils, तेल=Oil, चाय=Tea, नमक=Salt, चीनी=Sugar, घी=Ghee, दही=Curd, पनीर=Paneer, प्याज=Onion, आलू=Potato, टमाटर=Tomato, मिर्च=Chilli

IMPORTANT: This is an Indian grocery shopping list. Common items include:
- Rice varieties: Basmati Rice, Regular Rice, Sona Masoori
- Beverages: Bisleri Water, Coca Cola, Pepsi, Tea (चाय), Coffee
- Staples: Atta (आटा), Maida, Sugar (चीनी), Salt (नमक), Oil (तेल)
- Pulses: Dal (दाल), Moong Dal, Toor Dal, Chana Dal
- Spices: Turmeric (हल्दी), Red Chili (लाल मिर्च), Coriander (धनिया)
- Dairy: Milk (दूध), Paneer (पनीर), Curd (दही), Butter, Ghee (घी)
- Snacks: Biscuits, Namkeen, Chips

READ CAREFULLY - Common handwriting mistakes to avoid:
- "Basmati" should NOT be read as "Biscuit" or "Biskuit"
- "Bisleri" should NOT be read as "Biscuit" or "Biskuit"
- Hindi script letters are VALID text, NOT illegible scribbles

For each item, return a JSON object with these fields:
- `raw_text`: The EXACT text written (keep Hindi as-is, e.g., "दाल-5")
- `search_term_english`: English translation/transliteration for product search. For Hindi text like "दाल" → "Lentils" or "Dal". For "चावल" → "Rice". NEVER set to null for readable Hindi text.
- `req_qty`: Numeric quantity (e.g., 2, 5). If written as "दाल-5", the qty is 5. Default to 1 if not specified.
- `req_unit`: Unit of measurement (e.g., "gm", "kg", "ml", "L", "piece"). Default to "piece".
- `price`: Price of the item if written (e.g., ₹50), use numeric value only. Default to 0 if not specified.
- `is_brand_specified`: Boolean, true if a specific brand is mentioned.
- `confidence_score`: 0 to 1. Hindi text you can read = 0.85+. Mixed/unclear text = 0.5-0.8. Only truly illegible = < 0.4.
- `is_unreadable`: Boolean. Set to true ONLY if the text is completely illegible (random scribbles, ink blobs). DO NOT set to true for readable Hindi/Devanagari text.

Return a strictly valid JSON array. No markdown, no code blocks, just the raw JSON array.

Example with Hindi input (दूध-2, दाल-5):
[
  {
    "raw_text": "दूध-2",
    "search_term_english": "Milk",
    "req_qty": 2,
    "req_unit": "piece",
    "is_brand_specified": false,
    "confidence_score": 0.90,
    "is_unreadable": false
  },
  {
    "raw_text": "दाल-5",
    "search_term_english": "Lentils",
    "req_qty": 5,
    "req_unit": "piece",
    "is_brand_specified": false,
    "confidence_score": 0.90,
    "is_unreadable": false
  }
]

Example with English input:
[
  {
    "raw_text": "Basmati Rice",
    "search_term_english": "Basmati Rice",
    "req_qty": 1,
    "req_unit": "kg",
    "is_brand_specified": false,
    "confidence_score": 0.95,
    "is_unreadable": false
  }
]"""

        # 1. Try Groq Vision if available
        if self.is_available():
            try:
                # Encode image to base64
                image_base64 = base64.b64encode(image_data).decode("utf-8")
                media_type = f"image/{image_format}"
                if image_format == "jpg":
                    media_type = "image/jpeg"

                async with httpx.AsyncClient(timeout=60.0) as client:
                    payload = {
                        "model": settings.GROQ_VISION_MODEL,
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are a JSON-only OCR extraction API. You MUST respond with ONLY a valid JSON array of items. No explanations, no markdown, no commentary, no text before or after the JSON array. Start your response directly with the opening bracket of the array."
                            },
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
                        "max_tokens": 2048,
                        "temperature": 0.0
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

                    if response.status_code == 200:
                        result = response.json()
                        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                        if content:
                            logger.info(f"Successfully extracted OCR text via Groq: {content[:100]}...")
                            return self._parse_ocr_json(content)
                    elif response.status_code == 401:
                        logger.error("Groq API key is invalid (401).")
                        return {
                            "success": False,
                            "raw_text": "",
                            "error": "Groq API key is invalid"
                        }
                    else:
                        logger.error(f"Groq API non-200 response ({response.status_code}): {response.text}")
                        return {
                            "success": False,
                            "raw_text": "",
                            "error": f"Groq execution failed with status {response.status_code}"
                        }
                        
            except Exception as e:
                logger.error(f"Groq OCR failed: {e}")
                return {
                    "success": False,
                    "raw_text": "",
                    "error": str(e)
                }
        else:
            logger.error("Groq not available (no API key configured)")
            return {
                "success": False,
                "raw_text": "",
                "error": "Groq API key not configured"
            }

    # ==================== Store Inventory OCR ====================

    async def extract_inventory_items(
        self,
        image_data: bytes,
        image_format: str = "jpeg"
    ) -> Dict[str, Any]:
        """
        Extract inventory items (with PRICE and QUANTITY) from a store inventory image.
        Unlike extract_shopping_list, this focuses on price and stock quantity extraction.
        """
        if not self.is_available():
            return self._mock_ocr_response()

        image_base64 = base64.b64encode(image_data).decode("utf-8")
        media_type = f"image/{image_format}"
        if image_format == "jpg":
            media_type = "image/jpeg"

        prompt = """You are an OCR assistant for a STORE OWNER who wants to add products to their inventory system.

The image contains a LIST of products. Each product likely has:
- A PRODUCT NAME
- A PRICE (in ₹ / Rs / rupees). Look for numbers near the item name - these are prices.
- A QUANTITY / STOCK COUNT. Look for numbers indicating how many units.
- Sometimes a WEIGHT or UNIT (kg, g, ml, L, piece, packet, etc.)

CRITICAL INSTRUCTIONS:
- You MUST extract the PRICE for each item. Look for ₹ signs, "Rs", or any number written next to the product name that represents cost. Prices are usually numbers like 30, 50, 120, 250, etc.
- You MUST extract the QUANTITY for each item. This is how many units are in stock. Could be written as "x2", "qty: 5", just a number, etc.
- If the weight is part of the product description (e.g. "Rice 5kg"), that is NOT the quantity. The quantity is how many packets/units.
- Read Hindi/Devanagari text if present and translate to English.

For each item, return a JSON object with:
- `name`: Product name in English
- `raw_text`: Exact text as written in the image
- `price`: Price as a NUMBER (e.g. 50, not "₹50"). Default 0 only if truly not visible.
- `quantity`: Stock quantity as a NUMBER (e.g. 5). Default 1 only if truly not visible.
- `unit`: Unit like "kg", "g", "ml", "L", "piece", "packet". Default "piece".

Return ONLY a valid JSON array. No text, no explanation, just the JSON array starting with [

Example:
[
  {"name": "Tata Salt", "raw_text": "Tata Salt 1kg - ₹28", "price": 28, "quantity": 1, "unit": "kg"},
  {"name": "Aashirvaad Atta", "raw_text": "Aashirvaad Atta 5kg x3 ₹250", "price": 250, "quantity": 3, "unit": "piece"},
  {"name": "Amul Butter", "raw_text": "Amul Butter 100g Rs.52", "price": 52, "quantity": 1, "unit": "piece"}
]"""

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                payload = {
                    "model": settings.GROQ_VISION_MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a JSON-only inventory extraction API. Respond with ONLY a JSON array. Extract product name, price, and quantity from the image. Start directly with ["
                        },
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
                    "max_tokens": 2048,
                    "temperature": 0.0
                }

                logger.info("Calling Groq Vision for INVENTORY extraction")
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.groq_api_key}",
                        "Content-Type": "application/json"
                    },
                    json=payload
                )

                if response.status_code == 200:
                    result = response.json()
                    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if content:
                        logger.info(f"Inventory OCR response: {content[:200]}...")
                        return self._parse_inventory_json(content)
                else:
                    logger.error(f"Groq API error ({response.status_code}): {response.text}")

        except Exception as e:
            logger.error(f"Inventory OCR error: {e}")

        return {"success": False, "items": [], "raw_text": ""}

    def _parse_inventory_json(self, content: str) -> Dict[str, Any]:
        """Parse the inventory extraction JSON response"""
        import re
        content = content.strip()
        # Strip markdown code blocks
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        try:
            parsed = json.loads(content)
            items = parsed if isinstance(parsed, list) else parsed.get("items", parsed.get("products", []))
        except json.JSONDecodeError:
            # Fallback: find longest JSON array
            all_arrays = re.findall(r'\[\s*\{[\s\S]*?\}\s*\]', content)
            if not all_arrays:
                return {"success": False, "items": [], "raw_text": content}
            all_arrays.sort(key=len, reverse=True)
            items = []
            for arr_str in all_arrays:
                try:
                    items = json.loads(arr_str)
                    break
                except Exception:
                    continue

        if not isinstance(items, list):
            items = []

        validated = []
        for item in items:
            if isinstance(item, dict):
                validated.append({
                    "name": item.get("name", "Unknown"),
                    "raw_text": item.get("raw_text", ""),
                    "price": item.get("price", 0),
                    "quantity": item.get("quantity", 1),
                    "unit": item.get("unit", "piece"),
                })

        return {
            "success": True,
            "items": validated,
            "raw_text": json.dumps(validated, indent=2),
        }

    def _parse_ocr_json(self, content: str) -> Dict[str, Any]:
        """Helper method to parse JSON response from LLM"""
        try:
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            parsed = json.loads(content)
            
            # Handle both formats: raw array OR object with "items" key
            if isinstance(parsed, list):
                items = parsed
            elif isinstance(parsed, dict):
                items = parsed.get("items", parsed.get("products", []))
                if not isinstance(items, list):
                    items = []
            else:
                items = []
            
            validated_items = []
            for item in items:
                if isinstance(item, dict):
                    validated_items.append(item)
                    
            return {
                "success": True,
                "raw_text": json.dumps(validated_items, indent=2),
                "items": validated_items,
                "confidence": 0.95
            }
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            import re
            # Find ALL JSON arrays in the response and pick the longest valid one
            all_arrays = re.findall(r'\[\s*\{[\s\S]*?\}\s*\]', content)
            if not all_arrays:
                # Try simpler pattern for any array
                all_arrays = re.findall(r'\[[\s\S]*?\]', content)
            
            # Try each match, longest first (most likely to be the real data)
            all_arrays.sort(key=len, reverse=True)
            for arr_str in all_arrays:
                try:
                    parsed = json.loads(arr_str)
                    if isinstance(parsed, list) and len(parsed) > 0:
                        return {
                            "success": True,
                            "raw_text": json.dumps(parsed, indent=2),
                            "items": [i for i in parsed if isinstance(i, dict)],
                            "confidence": 0.90
                        }
                except Exception:
                    continue
                    
            return {
                "success": False,
                "raw_text": content,
                "error": "Failed to parse AI response",
                "items": []
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
