"""
Intent Classification Service using AWS Bedrock Nova Pro
Outputs fixed JSON structure for Nova Sonic to process
Uses reasoning model for better Hindi/Hinglish understanding
"""
import os
import json
import logging
from typing import Optional, Dict, List
import boto3

logger = logging.getLogger(__name__)

class IntentClassifier:
    """
    Classifies user intent using AWS Bedrock Nova Pro (reasoning model)
    Better at understanding Hindi/Hinglish context and confirmations
    """
    
    def __init__(self):
        self.bedrock = boto3.client(
            'bedrock-runtime',
            region_name=os.getenv('AWS_REGION', 'us-east-1')
        )
        self.model_id = "amazon.nova-pro-v1:0"  # Reasoning model
    
    async def classify_confirmation(
        self,
        user_text: str,
        pending_action: Optional[Dict] = None
    ) -> Dict:
        """
        Classify if user is confirming (yes/kardo), denying (no/nahi), 
        or asking a new question
        
        Returns:
            {
                "decision": "yes" | "no" | "unclear" | "new_query",
                "confidence": 0.0-1.0,
                "reasoning": str
            }
        """
        
        # --- Keyword fast path — skip Bedrock for obvious cases ---
        text_lower = user_text.strip().lower()
        
        # CANCEL keywords — checked FIRST in all non-IDLE states
        CANCEL_KEYWORDS = {'cancel', 'chhod do', 'chhodo', 'rehne do', 'nahi chahiye',
                           'mat karo', 'band karo', 'kuch nahi', 'jaane do', 'ruko',
                           'rehne de', 'chhod de', 'mat kar'}
        if text_lower in CANCEL_KEYWORDS:
            logger.info(f"🛑 Fast confirm: CANCEL (keyword: '{text_lower}')")
            return {"decision": "cancel", "confidence": 0.95, "reasoning": f"cancel keyword: '{text_lower}'"}
        
        YES_KEYWORDS = {'kardo', 'kar do', 'kr do', 'card', 'yes', 'haan', 'ha', 'ok',
                        'theek', 'theek hai', 'ji', 'ji haan', 'bilkul', 'zaroor',
                        'add karo', 'add kardo', 'daal do', 'le lo'}
        NO_KEYWORDS = {'nahi', 'no', 'mat', 'nhi', 'hata do'}
        
        if text_lower in YES_KEYWORDS:
            logger.info(f"⚡ Fast confirm: YES (keyword: '{text_lower}')")
            return {"decision": "yes", "confidence": 0.95, "reasoning": f"keyword fast-path: '{text_lower}'"}
        if text_lower in NO_KEYWORDS:
            logger.info(f"⚡ Fast confirm: NO (keyword: '{text_lower}')")
            return {"decision": "no", "confidence": 0.95, "reasoning": f"keyword fast-path: '{text_lower}'"}
        
        # Fall through to Bedrock for ambiguous cases
        context = ""
        if pending_action:
            action = pending_action.get('action', 'add')
            if 'product' in pending_action:
                product_name = pending_action['product'].get('name', 'item')
            else:
                product_name = "item"
            context = f"\nPending Action: {action} {product_name}"
        
        prompt = f"""You are analyzing a voice shopping conversation in Hindi/Hinglish.

User just said: "{user_text}"{context}

TASK: Determine if the user is:
1. CONFIRMING (yes/kardo/haan/theek hai/ok)
2. DENYING (no/nahi/mat karo)
3. UNCLEAR (mumbled/unclear audio)
4. NEW_QUERY (asking about a different product)

CRITICAL: "kardo", "kar do", "kr do", "card" (misheard) = CONFIRMING (yes)
CRITICAL: "nahi", "mat karo", "no" = DENYING (no)

Consider:
- Hindi/Hinglish variations
- Speech-to-text errors (e.g., "card" might be "kardo")
- Context of pending action

Output ONLY this JSON:
{{
    "decision": "yes|no|unclear|new_query",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation"
}}"""

        try:
            response = self.bedrock.converse(
                modelId=self.model_id,
                messages=[{
                    "role": "user",
                    "content": [{"text": prompt}]
                }],
                inferenceConfig={
                    "temperature": 0.1,
                    "maxTokens": 150
                }
            )
            
            content = response['output']['message']['content'][0]['text']
            
            # Extract JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            classification = json.loads(content)
            logger.info(f"🤔 Confirmation: {classification['decision']} (confidence: {classification['confidence']}) - {user_text}")
            return classification
            
        except Exception as e:
            logger.error(f"Bedrock confirmation classification error: {e}")
            # Fallback — use exact set matching (no substrings)
            FALLBACK_YES = {'kardo', 'kar do', 'card', 'yes', 'haan', 'ha', 'ok', 'theek', 'theek hai', 'ji'}
            FALLBACK_NO = {'nahi', 'no', 'mat', 'nhi'}
            FALLBACK_CANCEL = {'cancel', 'chhod do', 'rehne do', 'nahi chahiye', 'mat karo'}
            if text_lower in FALLBACK_CANCEL:
                return {"decision": "cancel", "confidence": 0.8, "reasoning": "cancel fallback"}
            elif text_lower in FALLBACK_YES:
                return {"decision": "yes", "confidence": 0.8, "reasoning": "keyword match fallback"}
            elif text_lower in FALLBACK_NO:
                return {"decision": "no", "confidence": 0.8, "reasoning": "keyword match fallback"}
            else:
                return {"decision": "unclear", "confidence": 0.3, "reasoning": "error fallback"}
    
    async def classify_existing_item_intent(
        self,
        user_text: str,
        product_name: str,
        current_quantity: float
    ) -> Dict:
        """
        When item is already in cart, classify what user wants to do:
        - add_more: Add additional quantity
        - update: Change to specific quantity
        - remove: Remove from cart
        - unclear: Need clarification
        
        Returns:
            {
                "action": "add_more" | "update" | "remove" | "unclear",
                "quantity": float | null,
                "confidence": 0.0-1.0
            }
        """
        
        prompt = f"""User is asking about an item ALREADY in their cart.

Product: {product_name}
Current Quantity in Cart: {current_quantity}
User Said: "{user_text}"

TASK: Determine what user wants:
1. ADD_MORE - Add additional quantity ("aur add karo", "ek aur", "haan")
2. UPDATE - Change to specific quantity ("do kar do", "quantity badha do")
3. REMOVE - Remove from cart ("hata do", "nahi chahiye", "remove")
4. UNCLEAR - Not clear what they want

RULES:
- "haan", "kardo", "add karo" = ADD_MORE (add 1 more)
- "do kar do", "teen kar do" = UPDATE (change to that quantity)
- "hata do", "remove", "nahi" = REMOVE
- Extract quantity if mentioned (ek=1, do=2, teen=3)

Output ONLY this JSON:
{{
    "action": "add_more|update|remove|unclear",
    "quantity": 1.0 or null,
    "confidence": 0.0-1.0
}}"""

        try:
            response = self.bedrock.converse(
                modelId=self.model_id,
                messages=[{
                    "role": "user",
                    "content": [{"text": prompt}]
                }],
                inferenceConfig={
                    "temperature": 0.1,
                    "maxTokens": 100
                }
            )
            
            content = response['output']['message']['content'][0]['text']
            
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            result = json.loads(content)
            logger.info(f"🛒 Existing item intent: {result['action']} (qty: {result.get('quantity')}, confidence: {result['confidence']})")
            return result
            
        except Exception as e:
            logger.error(f"Existing item intent classification error: {e}")
            return {"action": "unclear", "quantity": None, "confidence": 0.0}
    
    async def classify_user_intent(
        self, 
        user_speech: str, 
        available_products: list,
        current_cart: dict = None
    ) -> Optional[Dict]:
        """
        Classify user intent using AWS Bedrock Nova Pro (reasoning model)
        
        Returns:
            {
                "action": "add" | "update" | "remove" | "query",
                "product_name": str | null,
                "brand": str | null,
                "quantity": float | null,
                "matched_products": [...]
            }
        """
        
        # Build product list
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
        
        prompt = f"""Classify user intent for voice shopping in Hindi/Hinglish. Output ONLY JSON.

User Said: "{user_speech}"
Available Products: {', '.join(product_list)}{cart_context}

ACTIONS:
- "query": User ASKING about product (uses "chahiye", "kya hai", "batao", "kitne ka", "price")
- "add": User wants to ADD to cart (uses "add", "daal do", "le lunga", OR mentions quantity + product, OR ends with "kardo")
- "update": User wants to CHANGE quantity of item IN CART (uses "quantity", "badhao", "kam karo", "X kar do")
- "remove": User wants to REMOVE item (uses "hata do", "remove", "nikaal do")

CRITICAL RULES:
1. "ek/do/teen/NUMBER + PRODUCT" → action is "add" with that quantity (ONLY if item NOT in cart)
2. "PRODUCT + kardo/card" → action is "add" with quantity 1 (ONLY if item NOT in cart)
3. ONLY use "query" if user is ASKING (question words: "kya", "kitne", "batao")
4. For "update": determine if quantity is ABSOLUTE or RELATIVE:
   - ABSOLUTE (is_relative=false): "milk ki quantity do kardo" → set qty TO 2
   - RELATIVE (is_relative=true): "do aur milk daal do" → add 2 MORE, "ek kam kardo" → subtract 1
   - "double kardo" → is_relative=true, quantity=2 (multiply)
5. If item IS IN CART and user says "aur", "extra", "add kardo" → action is "update" with is_relative=true (NOT "add")
   - "sunflower oil 4 aur add kardo" → update, is_relative=true, qty=4 (add 4 more)
   - "milk do aur daal do" → update, is_relative=true, qty=2 (add 2 more)

EXTRACTION:
1. product_name: Generic type (e.g., "milk", "sugar", "bread", "basmati rice")
2. brand: Specific brand if mentioned, else null
3. quantity: Hindi numbers: ek=1, do=2, teen=3, char=4, paanch=5. null if not mentioned.
4. is_relative: true if user says "aur", "extra", "kam", "double" (relative change). false if setting absolute value. Only relevant for "update" action.

EXAMPLES:
- "milk" → {{"action": "query", "product_name": "milk", "brand": null, "quantity": null, "is_relative": false}}
- "ek milk" → {{"action": "add", "product_name": "milk", "brand": null, "quantity": 1, "is_relative": false}}
- "milk ki quantity do kardo" → {{"action": "update", "product_name": "milk", "brand": null, "quantity": 2, "is_relative": false}}
- "do aur milk daal do" → {{"action": "update", "product_name": "milk", "brand": null, "quantity": 2, "is_relative": true}}
- "sunflower oil 4 aur add kardo" → {{"action": "update", "product_name": "sunflower oil", "brand": null, "quantity": 4, "is_relative": true}}
- "ek milk kam kardo" → {{"action": "update", "product_name": "milk", "brand": null, "quantity": -1, "is_relative": true}}
- "milk hata do" → {{"action": "remove", "product_name": "milk", "brand": null, "quantity": null, "is_relative": false}}

Output ONLY this JSON:
{{
    "action": "add|update|remove|query",
    "product_name": "generic product type or null",
    "brand": "specific brand or null",
    "quantity": number or null,
    "is_relative": true or false
}}"""

        try:
            response = self.bedrock.converse(
                modelId=self.model_id,
                messages=[{
                    "role": "user",
                    "content": [{"text": prompt}]
                }],
                inferenceConfig={
                    "temperature": 0.1,
                    "maxTokens": 150
                }
            )
            
            content = response['output']['message']['content'][0]['text']
            
            # Extract JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            result = json.loads(content)
            
            # Validate action
            if result.get('action') not in ['add', 'update', 'remove', 'query']:
                return None
            
            action = result['action']
            product_name = result.get('product_name')
            brand = result.get('brand')
            quantity = result.get('quantity')
            is_relative = bool(result.get('is_relative', False))
            
            if not product_name:
                return None
            
            # Find matching products from inventory
            matched_products = self._find_matching_products(
                product_name, 
                brand, 
                available_products
            )
            
            if not matched_products:
                logger.warning(f"No products found in current context for: {product_name} (brand: {brand})")
            
            # Default quantity based on action
            if quantity is None:
                if action in ['add', 'remove']:
                    quantity = 1.0
                elif action == 'update':
                    quantity = 1.0
            
            rel_tag = ' (relative)' if is_relative else ''
            logger.info(f"🧠 Nova Pro: {action.upper()} {product_name} (brand: {brand}, qty: {quantity}{rel_tag}) → {len(matched_products)} matches")
            
            # Auto-promote QUERY→ADD when quantity is present
            if action == 'query' and quantity is not None:
                action = 'add'
                logger.info(f"🔄 Auto-promoted QUERY→ADD (quantity specified: {quantity})")
            
            return {
                'action': action,
                'product_name': product_name,
                'brand': brand,
                'quantity': float(quantity) if quantity is not None else None,
                'is_relative': is_relative,
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
        Flexible matching: "bread" matches "Egg Bread", "milk" matches "Toned Milk"
        Handles speech-to-text quirks like "m d h" for "MDH"
        """
        product_name_lower = product_name.lower()
        brand_lower = brand.lower() if brand else None
        
        # Also try concatenated version for letter-by-letter transcriptions 
        # e.g., "m d h" → "mdh"
        product_name_concat = product_name_lower.replace(' ', '')
        brand_concat = brand_lower.replace(' ', '') if brand_lower else None
        
        matches = []
        
        # If brand specified, try exact brand match first
        if brand_lower:
            for product in available_products:
                prod_name = product.get('name', '').lower()
                prod_brand = product.get('brand', '').lower()
                prod_name_concat = prod_name.replace(' ', '')
                prod_brand_concat = prod_brand.replace(' ', '')
                
                # Flexible name matching: check if ANY word from query appears in product name
                query_words = [w for w in product_name_lower.split() if len(w) >= 3]
                name_match = any(word in prod_name for word in query_words) if query_words else False
                # Also try concatenated match
                name_match = name_match or (len(product_name_concat) >= 3 and product_name_concat in prod_name_concat)
                
                if name_match:
                    # Check brand match (in product name OR brand field)
                    brand_in_name = brand_lower in prod_name or (brand_concat and len(brand_concat) >= 2 and brand_concat in prod_name_concat)
                    brand_in_field = brand_lower in prod_brand or prod_brand in brand_lower
                    brand_in_field = brand_in_field or (brand_concat and len(brand_concat) >= 2 and (brand_concat in prod_brand_concat or prod_brand_concat in brand_concat))
                    
                    if brand_in_name or brand_in_field:
                        matches.append(product)
            
            # If brand match found, return only those
            if matches:
                return matches
            
            # Also try brand-only matching (user might say "mdh" and mean "MDH Masala")
            for product in available_products:
                prod_name = product.get('name', '').lower()
                prod_brand = product.get('brand', '').lower()
                prod_name_concat = prod_name.replace(' ', '')
                prod_brand_concat = prod_brand.replace(' ', '')
                
                brand_in_name = brand_lower in prod_name or (brand_concat and len(brand_concat) >= 2 and brand_concat in prod_name_concat)
                brand_in_field = brand_lower in prod_brand or prod_brand in brand_lower
                brand_in_field = brand_in_field or (brand_concat and len(brand_concat) >= 2 and (brand_concat in prod_brand_concat or prod_brand_concat in brand_concat))
                
                if (brand_in_name or brand_in_field) and product not in matches:
                    matches.append(product)
            
            if matches:
                return matches
        
        # No brand specified OR no brand matches found - flexible name matching
        for product in available_products:
            prod_name = product.get('name', '').lower()
            prod_name_concat = prod_name.replace(' ', '')
            
            # Check if ANY significant word from query appears in product name
            query_words = [w for w in product_name_lower.split() if len(w) >= 3]
            name_match = any(word in prod_name for word in query_words) if query_words else False
            # Also try concatenated match for abbreviations
            name_match = name_match or (len(product_name_concat) >= 3 and product_name_concat in prod_name_concat)
            
            if name_match and product not in matches:
                matches.append(product)
        
        return matches
    
    async def classify_ai_response(
        self,
        ai_text: str,
        pending_action: Optional[Dict] = None
    ) -> Dict:
        """
        Classify AI response to determine if it's confirming an action
        
        Returns:
            {
                "decision": "confirmed" | "question" | "info",
                "confidence": 0.0-1.0
            }
        """
        
        prompt = f"""Classify this AI shopkeeper response.

AI said: "{ai_text}"

Is the AI:
1. CONFIRMED - Confirming action completed ("add kar diya", "hata diya")
2. QUESTION - Asking user a question ("Add kar dun?", "Kaunsa chahiye?")
3. INFO - Providing information only

Output ONLY JSON:
{{
    "decision": "confirmed|question|info",
    "confidence": 0.0-1.0
}}"""

        try:
            response = self.bedrock.converse(
                modelId=self.model_id,
                messages=[{
                    "role": "user",
                    "content": [{"text": prompt}]
                }],
                inferenceConfig={
                    "temperature": 0.1,
                    "maxTokens": 50
                }
            )
            
            content = response['output']['message']['content'][0]['text']
            
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            result = json.loads(content)
            logger.info(f"🧠 AI Response Classification: {result['decision']} (confidence: {result['confidence']}) for: '{ai_text[:50]}'")
            return result
            
        except Exception as e:
            logger.error(f"AI response classification error: {e}")
            # Fallback
            ai_lower = ai_text.lower()
            if any(phrase in ai_lower for phrase in ['add kar diya', 'hata diya', 'kar di']):
                return {"decision": "confirmed", "confidence": 0.8}
            elif '?' in ai_text:
                return {"decision": "question", "confidence": 0.8}
            else:
                return {"decision": "info", "confidence": 0.5}
