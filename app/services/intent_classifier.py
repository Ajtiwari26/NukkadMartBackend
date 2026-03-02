"""
Intent Classification Service using Groq
Outputs fixed JSON structure for Nova Sonic to process
"""
import os
import json
import logging
from groq import Groq
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

class IntentClassifier:
    """
    Classifies user intent and outputs fixed JSON structure
    Nova Sonic uses this JSON to decide what to do
    """
    
    def __init__(self):
        self.client = Groq(api_key=os.getenv('GROQ_API_KEY'))
        self.model = "llama-3.3-70b-versatile"
    
    async def classify_user_intent(
        self, 
        user_speech: str, 
        available_products: list,
        current_cart: dict = None
    ) -> Optional[Dict]:
        """
        Classify user intent and return fixed JSON structure
        
        Returns:
            {
                "action": "add" | "update" | "remove" | "query",
                "product_name": str | null,  # Generic name (e.g., "milk", "sugar")
                "brand": str | null,  # Specific brand if mentioned
                "quantity": float | null,  # null for query without quantity
                "matched_products": [...]  # All matching products from inventory
            }
        """
        
        # Build product list with brands
        product_list = []
        for p in available_products[:20]:
            product_list.append(f"{p.get('name')} ({p.get('brand', 'Local')})")
        
        # Build cart context
        cart_context = ""
        if current_cart:
            cart_items = []
            for product in available_products:
                prod_id = product.get('id', product.get('_id', ''))
                if str(prod_id) in current_cart:
                    qty = current_cart[str(prod_id)]
                    cart_items.append(f"{product.get('name')}: {qty}")
            if cart_items:
                cart_context = f"\n\nCurrent Cart:\n" + "\n".join(cart_items)
        
        prompt = f"""Classify user intent for voice shopping. Output ONLY JSON.

User Said: "{user_speech}"
Available Products: {', '.join(product_list)}{cart_context}

ACTIONS:
- "query": User ASKING about product (uses "chahiye", "kya hai", "batao", OR mentions product without command)
- "add": User EXPLICITLY wants to ADD (uses "add kar do", "daal do", "le lunga")
- "update": User wants to CHANGE quantity of item IN CART (uses "quantity X kar do", "X aur add")
- "remove": User wants to REMOVE item (uses "hata do", "remove", "nikaal do")

EXTRACTION RULES:
1. product_name: Generic product type (e.g., "milk", "sugar", "bread")
2. brand: Specific brand if mentioned (e.g., "Amul", "Tata"), else null
3. quantity: Number mentioned, null if not specified
4. For QUERY: quantity can be null (user just asking about product)
5. For ADD/UPDATE/REMOVE: quantity defaults to 1 if not specified

EXAMPLES:
- "milk chahiye" → {{"action": "query", "product_name": "milk", "brand": null, "quantity": null}}
- "Amul milk chahiye" → {{"action": "query", "product_name": "milk", "brand": "Amul", "quantity": null}}
- "ek kilo sugar" → {{"action": "query", "product_name": "sugar", "brand": null, "quantity": 1}}
- "teen paneer add kar do" → {{"action": "add", "product_name": "paneer", "brand": null, "quantity": 3}}
- "Amul paneer add kar do" → {{"action": "add", "product_name": "paneer", "brand": "Amul", "quantity": 1}}
- "bread hata do" → {{"action": "remove", "product_name": "bread", "brand": null, "quantity": 1}}
- "cart mein jo do hai usko teen kar do" → {{"action": "update", "product_name": "paneer", "brand": null, "quantity": 3}}

Output ONLY this JSON (no extra text):
{{
    "action": "add|update|remove|query",
    "product_name": "generic product type or null",
    "brand": "specific brand or null",
    "quantity": 1.0 or null
}}"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=100,
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # Extract JSON
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()
            
            result = json.loads(result_text)
            
            # Validate action
            if result.get('action') not in ['add', 'update', 'remove', 'query']:
                return None
            
            action = result['action']
            product_name = result.get('product_name')
            brand = result.get('brand')
            quantity = result.get('quantity')
            
            if not product_name:
                return None
            
            # Find matching products from inventory
            matched_products = self._find_matching_products(
                product_name, 
                brand, 
                available_products
            )
            
            if not matched_products:
                logger.warning(f"No products found for: {product_name} (brand: {brand})")
                return None
            
            # Default quantity based on action
            if quantity is None:
                if action in ['add', 'remove']:
                    quantity = 1.0
                elif action == 'update':
                    quantity = 1.0
                # For query, quantity can remain None
            
            logger.info(f"🧠 Groq: {action.upper()} {product_name} (brand: {brand}, qty: {quantity}) → {len(matched_products)} matches")
            
            return {
                'action': action,
                'product_name': product_name,
                'brand': brand,
                'quantity': float(quantity) if quantity is not None else None,
                'matched_products': matched_products
            }
            
        except Exception as e:
            logger.error(f"Intent classification error: {e}")
            return None
    
    def _find_matching_products(
        self, 
        product_name: str, 
        brand: Optional[str], 
        available_products: list
    ) -> List[Dict]:
        """
        Find all products matching the product name and optional brand
        
        Returns list of matching products, prioritizing:
        1. Exact brand match if brand specified
        2. All products with matching product type if no brand
        """
        product_name_lower = product_name.lower()
        brand_lower = brand.lower() if brand else None
        
        matches = []
        
        for product in available_products:
            prod_name = product.get('name', '').lower()
            prod_brand = product.get('brand', '').lower()
            
            # Check if product name matches
            name_match = (
                product_name_lower in prod_name or 
                prod_name in product_name_lower or
                any(word in prod_name for word in product_name_lower.split())
            )
            
            if name_match:
                # If brand specified, check brand match
                if brand_lower:
                    if brand_lower in prod_brand or prod_brand in brand_lower:
                        matches.append(product)
                else:
                    # No brand specified, add all matching products
                    matches.append(product)
        
        return matches
