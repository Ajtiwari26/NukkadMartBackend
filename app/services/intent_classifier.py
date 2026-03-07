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
1. CONFIRMING → decision: "yes" (kardo/haan/theek hai/ok)
2. DENYING → decision: "no" (nahi/mat karo/nahi chahiye)
3. UNCLEAR → decision: "unclear" (mumbled/unclear audio)
4. NEW_QUERY → decision: "new_query" (asking about a different product)

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
            # Normalize decision values — LLM sometimes returns 'denying'/'confirming' instead of 'no'/'yes'
            decision_map = {'denying': 'no', 'deny': 'no', 'confirming': 'yes', 'confirm': 'yes',
                           'confirmed': 'yes', 'denied': 'no', 'cancelled': 'cancel', 'cancelling': 'cancel'}
            raw_decision = classification['decision'].lower()
            classification['decision'] = decision_map.get(raw_decision, raw_decision)
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
        current_cart: dict = None,
        last_product_name: str = None
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
        
        # Build pronoun context
        pronoun_context = ""
        if last_product_name:
            pronoun_context = f"\nLast Discussed Product: {last_product_name} (if user says 'isko', 'ise', 'ye wala', 'this', it refers to this product)"
        
        prompt = f"""Classify user intent for voice shopping in Hindi/Hinglish. Output ONLY JSON.

User Said: "{user_speech}"
Available Products: {', '.join(product_list)}{cart_context}{pronoun_context}

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

PRODUCT MATCHING (MOST IMPORTANT):
"matched_product" must be the EXACT product name from "Available Products" that best matches what the user is asking for.
Think step by step:
1. What did the user say? (could be Hindi, Marathi, Tamil, Bengali, Punjabi, English, or misspelled)
2. What does that word MEAN? (translate to English if needed: haldee/haldi/halldi = turmeric, gud/gur/good = jaggery, batata/aloo = potato, doodh/dudh = milk, jal/paani = water, chawal = rice, cheeni = sugar, tel = oil, atta = flour, dahi = curd, makhan = butter)
3. Does it SOUND LIKE any product? (koffe → coffee, jaigiri → jaggery, biscoot → biscuits)
4. Which product from "Available Products" matches? Output that EXACT name.
If NO product matches even after translation, set matched_product to null.

EXTRACTION:
1. product_name: What the user actually said (for logging)
2. matched_product: The EXACT name from "Available Products" that matches. null if nothing matches.
3. brand: Specific brand if mentioned, else null
4. quantity: Hindi numbers: ek=1, do=2, teen=3, char=4, paanch=5. null if not mentioned.
5. is_relative: true if user says "aur", "extra", "kam", "double" (relative change). false if setting absolute value.

EXAMPLES:
- "haldee do packet" → {{"action": "add", "product_name": "haldee", "matched_product": "Turmeric Powder (500g)", "brand": null, "quantity": 2, "is_relative": false}}
- "batata chahiye" → {{"action": "query", "product_name": "batata", "matched_product": "Potato (1kg)", "brand": null, "quantity": null, "is_relative": false}}
- "ek milk" → {{"action": "add", "product_name": "milk", "matched_product": "Toned Milk (500ml)", "brand": null, "quantity": 1, "is_relative": false}}
- "gud daal do" → {{"action": "add", "product_name": "gud", "matched_product": "Jaggery Gur (500g)", "brand": null, "quantity": 1, "is_relative": false}}

Output ONLY this JSON:
{{
    "action": "add|update|remove|query",
    "product_name": "what user said",
    "matched_product": "EXACT name from Available Products or null",
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
                    "maxTokens": 200
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
            matched_product_name = result.get('matched_product')  # LLM's primary match
            brand = result.get('brand')
            quantity = result.get('quantity')
            is_relative = bool(result.get('is_relative', False))
            
            if not product_name and not matched_product_name:
                return None
            
            matched_products = []
            
            # === PRIMARY: Use LLM's matched_product (exact name from inventory) ===
            if matched_product_name:
                mp_lower = matched_product_name.lower()
                for p in available_products:
                    if mp_lower in p.get('name', '').lower() or p.get('name', '').lower() in mp_lower:
                        matched_products.append(p)
                
                if matched_products:
                    logger.info(f"🌐 LLM matched: '{product_name}' → '{matched_product_name}' → {len(matched_products)} products")
                    product_name = matched_product_name  # Use the resolved name for downstream
            
            # === FALLBACK: keyword/fuzzy matching if LLM match failed ===
            if not matched_products and product_name:
                matched_products = self._find_matching_products(
                    product_name, brand, available_products
                )
            
            if not matched_products:
                logger.warning(f"No products found for: '{product_name}' (LLM matched: '{matched_product_name}', brand: {brand})")
            
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
    
    # Multilingual alias dictionary: maps common Hindi/regional/slang names → inventory names
    PRODUCT_ALIASES = {
        # Dairy
        'doodh': 'milk', 'dudh': 'milk', 'dood': 'milk',
        # Sweeteners
        'gud': 'jaggery', 'gur': 'jaggery', 'gurd': 'jaggery', 'good': 'jaggery',
        'jaigiri': 'jaggery', 'jaigri': 'jaggery', 'jagiri': 'jaggery', 'jagri': 'jaggery',
        'gulkand': 'jaggery', 'gulko': 'jaggery',
        'cheeni': 'sugar', 'chini': 'sugar', 'shakkar': 'sugar',
        # Grains
        'chawal': 'rice', 'chaawal': 'rice', 'chaval': 'rice',
        'atta': 'wheat flour', 'aata': 'wheat flour', 'gehu': 'wheat',
        'maida': 'refined flour', 'besan': 'gram flour',
        'daal': 'dal', 'dal': 'dal', 'daaal': 'dal',
        # Oil
        'tel': 'oil', 'tail': 'oil',
        # Bread
        'roti': 'bread', 'pav': 'bread', 'paav': 'bread',
        # Beverages
        'chai': 'tea', 'chaay': 'tea', 'chay': 'tea',
        'koffe': 'coffee', 'koffee': 'coffee', 'kafi': 'coffee', 'kaafi': 'coffee',
        # Spices
        'namak': 'salt', 'noon': 'salt',
        'mirch': 'chilli', 'mirchi': 'chilli', 'laal mirch': 'red chilli',
        'haldi': 'turmeric', 'haldy': 'turmeric', 'haldee': 'turmeric', 'halde': 'turmeric',
        'dhaniya': 'coriander', 'dhaniye': 'coriander',
        'jeera': 'cumin', 'zeera': 'cumin',
        'elaichi': 'cardamom', 'ilaychi': 'cardamom',
        'laung': 'clove', 'dalchini': 'cinnamon',
        # Vegetables & Fruits
        'aloo': 'potato', 'aaloo': 'potato',
        'pyaz': 'onion', 'pyaaz': 'onion', 'pyaj': 'onion',
        'tamatar': 'tomato', 'tamaatar': 'tomato',
        'adrak': 'ginger', 'lehsun': 'garlic', 'lahsun': 'garlic',
        'palak': 'spinach', 'gobhi': 'cauliflower', 'gobi': 'cauliflower',
        'matar': 'peas', 'mattar': 'peas',
        'seb': 'apple', 'kela': 'banana', 'santara': 'orange', 'aam': 'mango',
        'nimbu': 'lemon', 'nimboo': 'lemon',
        # Snacks
        'biscuit': 'biscuits', 'biskut': 'biscuits', 'biskit': 'biscuits',
        'chips': 'chips', 'namkeen': 'namkeen', 'namkin': 'namkeen',
        'maggi': 'noodles', 'noodle': 'noodles',
        # Common
        'sabun': 'soap', 'shampoo': 'shampoo',
        'pani': 'water', 'paani': 'water',
        'ghee': 'ghee', 'makhan': 'butter', 'makkhan': 'butter',
        'dahi': 'curd', 'dahee': 'curd',
        'paneer': 'paneer', 'panir': 'paneer',
        'anda': 'egg', 'ande': 'egg',
    }
    
    def _resolve_aliases(self, product_name: str) -> List[str]:
        """Resolve product name through multilingual aliases. Returns list of possible names."""
        names = [product_name.lower()]
        
        # Check each word and the full name against aliases
        pn_lower = product_name.lower().strip()
        
        # Full name alias check
        if pn_lower in self.PRODUCT_ALIASES:
            names.append(self.PRODUCT_ALIASES[pn_lower])
        
        # Individual word alias check
        for word in pn_lower.split():
            if word in self.PRODUCT_ALIASES:
                names.append(self.PRODUCT_ALIASES[word])
        
        return list(set(names))
    
    def _fuzzy_match_products(
        self, 
        product_name: str, 
        available_products: list,
        threshold: float = 0.70  # Increased from 0.55 to reduce false positives
    ) -> List[Dict]:
        """
        Fuzzy match product name against available products using SequenceMatcher.
        Implements term weighting to prioritize rare/specific words over common ones.
        """
        from difflib import SequenceMatcher
        
        pn_lower = product_name.lower().strip()
        query_words = [w for w in pn_lower.split() if len(w) >= 3]
        
        if not query_words:
            return []
        
        # Calculate term weights (IDF-like scoring)
        # Words that appear in fewer products get higher weights
        term_weights = {}
        for word in query_words:
            count = sum(1 for p in available_products if word in p.get('name', '').lower())
            # Inverse frequency: rare words get higher weight
            term_weights[word] = 1.0 / (count + 1) if count > 0 else 1.0
        
        # Common generic words that should have low weight
        generic_words = {'packet', 'pack', 'box', 'bottle', 'bag', 'piece', 'kg', 'gm', 'ml', 'ltr'}
        for word in generic_words:
            if word in term_weights:
                term_weights[word] *= 0.3  # Reduce weight of generic words
        
        scored = []
        
        for product in available_products:
            prod_name = product.get('name', '').lower()
            prod_words = prod_name.split()
            
            # Calculate weighted score
            total_score = 0.0
            matched_important_word = False
            
            for query_word in query_words:
                weight = term_weights.get(query_word, 1.0)
                best_match_score = 0.0
                
                # Check against each product word
                for prod_word in prod_words:
                    if len(prod_word) >= 3:
                        similarity = SequenceMatcher(None, query_word, prod_word).ratio()
                        if similarity > best_match_score:
                            best_match_score = similarity
                
                # Apply weight to the match score
                weighted_score = best_match_score * weight
                total_score += weighted_score
                
                # Track if we matched an important (high-weight) word
                if best_match_score >= 0.75 and weight > 0.5:
                    matched_important_word = True
            
            # Normalize by number of query words
            avg_score = total_score / len(query_words) if query_words else 0
            
            # Require at least one strong match on an important word
            if avg_score >= threshold and matched_important_word:
                scored.append((avg_score, product))
        
        # Sort by score descending, return top matches
        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:5]]

    def _word_boundary_match(self, query_word: str, product_name: str) -> bool:
        """
        Match a query word against a product name using word-boundary rules.
        - Words >= 4 chars: standard substring match (e.g., 'mirchi' matches 'Red Mirchi Powder')
        - Words 3 chars: must match at start of a word boundary (prefix match).
          'mir' matches 'Mirchi' but NOT 'Kashmiri'
        - Words < 3 chars: ignored (too short to be meaningful)
        """
        if len(query_word) < 3:
            return False
        
        prod_words = product_name.split()
        
        if len(query_word) == 3:
            # Prefix-only match: query must start a word in the product name
            return any(pw.startswith(query_word) for pw in prod_words)
        else:
            # Standard substring match for 4+ char words
            return query_word in product_name
    
    def _score_match(self, query_words: List[str], product_name: str, available_products: list) -> float:
        """
        Score a product match using basic term weighting.
        Rarer words (appearing in fewer products) contribute more to the score.
        """
        if not query_words:
            return 0.0
        
        prod_name_lower = product_name.lower()
        total_score = 0.0
        matched_words = 0
        
        for word in query_words:
            if self._word_boundary_match(word, prod_name_lower):
                # Term frequency: how many products contain this word?
                # Fewer = rarer = higher weight
                doc_freq = sum(1 for p in available_products if word in p.get('name', '').lower())
                if doc_freq == 0:
                    doc_freq = 1
                # IDF-inspired weight: log(N/df) approximation
                import math
                weight = math.log(max(len(available_products), 1) / doc_freq + 1)
                total_score += weight
                matched_words += 1
        
        # Bonus for matching more query words
        if len(query_words) > 0:
            coverage = matched_words / len(query_words)
            total_score *= (0.5 + 0.5 * coverage)  # Coverage multiplier
        
        return total_score

    def _find_matching_products(
        self, 
        product_name: str, 
        brand: Optional[str], 
        available_products: list
    ) -> List[Dict]:
        """
        Find all products matching the product name and optional brand.
        Matching order: exact → alias expansion → fuzzy match.
        Uses tokenized prefix matching and term weighting for better ranking.
        """
        product_name_lower = product_name.lower()
        brand_lower = brand.lower() if brand else None
        
        # Also try concatenated version for letter-by-letter transcriptions 
        # e.g., "m d h" → "mdh"
        product_name_concat = product_name_lower.replace(' ', '')
        brand_concat = brand_lower.replace(' ', '') if brand_lower else None
        
        scored_matches = []  # (score, product) tuples
        seen_ids = set()
        
        # === STEP 1: Resolve multilingual aliases ===
        all_names = self._resolve_aliases(product_name)
        
        # If brand specified, try exact brand match first
        if brand_lower:
            for name_variant in all_names:
                name_concat = name_variant.replace(' ', '')
                query_words = [w for w in name_variant.split() if len(w) >= 3]
                
                for product in available_products:
                    prod_name = product.get('name', '').lower()
                    prod_brand = product.get('brand', '').lower()
                    prod_name_concat = prod_name.replace(' ', '')
                    prod_brand_concat = prod_brand.replace(' ', '')
                    
                    # Tokenized prefix matching (improved)
                    name_match = any(self._word_boundary_match(w, prod_name) for w in query_words) if query_words else False
                    name_match = name_match or (len(name_concat) >= 4 and name_concat in prod_name_concat)
                    
                    if name_match:
                        brand_in_name = brand_lower in prod_name or (brand_concat and len(brand_concat) >= 2 and brand_concat in prod_name_concat)
                        brand_in_field = brand_lower in prod_brand or prod_brand in brand_lower
                        brand_in_field = brand_in_field or (brand_concat and len(brand_concat) >= 2 and (brand_concat in prod_brand_concat or prod_brand_concat in brand_concat))
                        
                        pid = product.get('id', product.get('_id', id(product)))
                        if (brand_in_name or brand_in_field) and pid not in seen_ids:
                            score = self._score_match(query_words, prod_name, available_products)
                            scored_matches.append((score, product))
                            seen_ids.add(pid)
            
            if scored_matches:
                scored_matches.sort(key=lambda x: x[0], reverse=True)
                return [p for _, p in scored_matches]
            
            # Brand-only matching
            for product in available_products:
                prod_name = product.get('name', '').lower()
                prod_brand = product.get('brand', '').lower()
                prod_name_concat = prod_name.replace(' ', '')
                prod_brand_concat = prod_brand.replace(' ', '')
                
                brand_in_name = brand_lower in prod_name or (brand_concat and len(brand_concat) >= 2 and brand_concat in prod_name_concat)
                brand_in_field = brand_lower in prod_brand or prod_brand in brand_lower
                brand_in_field = brand_in_field or (brand_concat and len(brand_concat) >= 2 and (brand_concat in prod_brand_concat or prod_brand_concat in brand_concat))
                
                pid = product.get('id', product.get('_id', id(product)))
                if (brand_in_name or brand_in_field) and pid not in seen_ids:
                    scored_matches.append((1.0, product))
                    seen_ids.add(pid)
            
            if scored_matches:
                return [p for _, p in scored_matches]
        
        # === STEP 2: Flexible name matching with all alias variants ===
        for name_variant in all_names:
            name_concat = name_variant.replace(' ', '')
            query_words = [w for w in name_variant.split() if len(w) >= 3]
            
            for product in available_products:
                prod_name = product.get('name', '').lower()
                prod_name_concat = prod_name.replace(' ', '')
                
                # Tokenized prefix matching (improved)
                name_match = any(self._word_boundary_match(w, prod_name) for w in query_words) if query_words else False
                name_match = name_match or (len(name_concat) >= 4 and name_concat in prod_name_concat)
                
                pid = product.get('id', product.get('_id', id(product)))
                if name_match and pid not in seen_ids:
                    score = self._score_match(query_words, prod_name, available_products)
                    scored_matches.append((score, product))
                    seen_ids.add(pid)
        
        if scored_matches:
            # Sort by relevance score (highest first)
            scored_matches.sort(key=lambda x: x[0], reverse=True)
            logger.info(f"📊 Scored matches for '{product_name}': {[(round(s, 2), p.get('name')) for s, p in scored_matches[:5]]}")
            return [p for _, p in scored_matches]
        
        # === STEP 3: Fuzzy matching as fallback ===
        fuzzy_matches = self._fuzzy_match_products(product_name, available_products)
        if fuzzy_matches:
            logger.info(f"🔍 Fuzzy matched '{product_name}' → {[p.get('name') for p in fuzzy_matches]}")
        return fuzzy_matches
    
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
