"""
Inventory Service
Business logic for inventory management with MongoDB
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorDatabase
import uuid
import logging
from difflib import SequenceMatcher

from app.models.product import (
    ProductCreate,
    ProductUpdate,
    ProductInDB,
    ProductResponse,
    StockUpdate,
    StockUpdateResponse,
    StockOperation,
    InventoryAlert,
    InventorySummary
)
from app.models.inventory import (
    StockMovement,
    StockMovementType,
    InventoryItem,
    MatchedProduct,
    ProductMatchResponse
)
from app.db.redis import RedisClient

logger = logging.getLogger(__name__)


class InventoryService:
    """Service for managing store inventory"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.products = db.products
        self.stock_movements = db.stock_movements
        self.stores = db.stores

    # ==================== Product CRUD ====================

    async def create_product(self, product: ProductCreate) -> ProductInDB:
        """Create a new product"""
        product_id = f"PROD_{uuid.uuid4().hex[:8].upper()}"
        now = datetime.utcnow()

        product_doc = {
            "product_id": product_id,
            **product.model_dump(),
            "in_stock": product.stock_quantity > 0,
            "total_sold": 0,
            "view_count": 0,
            "created_at": now,
            "updated_at": now
        }

        # Add ONDC descriptor if not provided
        if product.ondc_info:
            product_doc["ondc_info"]["descriptor_name"] = product.name

        await self.products.insert_one(product_doc)

        # Update store product count
        await self.stores.update_one(
            {"store_id": product.store_id},
            {"$inc": {"total_products": 1}}
        )

        logger.info(f"Created product {product_id} for store {product.store_id}")

        return ProductInDB(**product_doc)

    async def get_product(self, product_id: str) -> Optional[ProductInDB]:
        """Get a product by ID"""
        product = await self.products.find_one({"product_id": product_id})
        if product:
            return ProductInDB(**product)
        return None

    async def get_product_by_barcode(self, barcode: str, store_id: str) -> Optional[ProductInDB]:
        """Get a product by barcode and store"""
        product = await self.products.find_one({
            "barcode": barcode,
            "store_id": store_id
        })
        if product:
            return ProductInDB(**product)
        return None

    async def update_product(self, product_id: str, update: ProductUpdate) -> Optional[ProductInDB]:
        """Update a product"""
        update_data = update.model_dump(exclude_unset=True)
        if not update_data:
            return await self.get_product(product_id)

        update_data["updated_at"] = datetime.utcnow()

        result = await self.products.find_one_and_update(
            {"product_id": product_id},
            {"$set": update_data},
            return_document=True
        )

        if result:
            logger.info(f"Updated product {product_id}")
            return ProductInDB(**result)
        return None

    async def delete_product(self, product_id: str) -> bool:
        """Soft delete a product (set is_active to False)"""
        result = await self.products.update_one(
            {"product_id": product_id},
            {
                "$set": {
                    "is_active": False,
                    "is_available": False,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        return result.modified_count > 0

    async def list_products(
        self,
        store_id: str,
        category: Optional[str] = None,
        subcategory: Optional[str] = None,
        in_stock_only: bool = False,
        is_active: bool = True,
        search_query: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "name",
        sort_order: int = 1
    ) -> Dict[str, Any]:
        """List products with filtering and pagination"""
        query = {"store_id": store_id, "is_active": is_active}

        if category:
            query["category"] = category
        if subcategory:
            query["subcategory"] = subcategory
        if in_stock_only:
            query["stock_quantity"] = {"$gt": 0}
        if search_query:
            query["$text"] = {"$search": search_query}

        # Get total count
        total = await self.products.count_documents(query)

        # Get paginated results
        skip = (page - 1) * page_size
        cursor = self.products.find(query).sort(sort_by, sort_order).skip(skip).limit(page_size)

        products = []
        async for doc in cursor:
            # Add default values for missing required fields
            if "gst_info" not in doc or doc["gst_info"] is None:
                doc["gst_info"] = {
                    "gst_rate": 5,
                    "hsn_code": "0000",
                    "is_gst_inclusive": True,
                    "cess_rate": 0
                }
            if "unit" not in doc:
                doc["unit"] = "piece"
            if "created_at" not in doc:
                doc["created_at"] = datetime.utcnow()
            if "updated_at" not in doc:
                doc["updated_at"] = datetime.utcnow()
            try:
                products.append(ProductInDB(**doc))
            except Exception as e:
                logger.warning(f"Skipping invalid product {doc.get('product_id')}: {e}")
                continue

        return {
            "products": products,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size
        }

    # ==================== Stock Management ====================

    async def update_stock(
        self,
        product_id: str,
        update: StockUpdate,
        user_id: Optional[str] = None
    ) -> Optional[StockUpdateResponse]:
        """Update product stock with movement tracking"""
        product = await self.products.find_one({"product_id": product_id})
        if not product:
            return None

        current_qty = product["stock_quantity"]
        store_id = product["store_id"]

        # Calculate new quantity based on operation
        if update.operation == StockOperation.SET:
            new_qty = update.quantity
        elif update.operation == StockOperation.ADD:
            new_qty = current_qty + update.quantity
        elif update.operation == StockOperation.SUBTRACT:
            new_qty = max(0, current_qty - update.quantity)
        elif update.operation == StockOperation.RESERVE:
            new_qty = max(0, current_qty - update.quantity)
        elif update.operation == StockOperation.RELEASE:
            new_qty = current_qty + update.quantity
        else:
            new_qty = update.quantity

        now = datetime.utcnow()

        # Update product
        await self.products.update_one(
            {"product_id": product_id},
            {
                "$set": {
                    "stock_quantity": new_qty,
                    "in_stock": new_qty > 0,
                    "updated_at": now
                }
            }
        )

        # Record stock movement
        movement_type = self._get_movement_type(update.operation)
        movement = {
            "movement_id": f"MOV_{uuid.uuid4().hex[:8].upper()}",
            "store_id": store_id,
            "product_id": product_id,
            "movement_type": movement_type,
            "quantity": new_qty - current_qty,
            "previous_quantity": current_qty,
            "new_quantity": new_qty,
            "reference_type": update.reference_id.split("_")[0] if update.reference_id else "manual",
            "reference_id": update.reference_id,
            "notes": update.reason,
            "created_by": user_id,
            "created_at": now
        }
        await self.stock_movements.insert_one(movement)

        # Invalidate Redis cache
        try:
            await RedisClient.invalidate_inventory(store_id, product_id)
        except Exception as e:
            logger.warning(f"Failed to invalidate cache: {e}")

        logger.info(f"Stock updated for {product_id}: {current_qty} -> {new_qty}")

        return StockUpdateResponse(
            product_id=product_id,
            previous_quantity=current_qty,
            new_quantity=new_qty,
            operation=update.operation,
            in_stock=new_qty > 0,
            updated_at=now
        )

    async def bulk_update_stock(
        self,
        store_id: str,
        updates: List[Dict],
        user_id: Optional[str] = None
    ) -> List[StockUpdateResponse]:
        """Bulk update stock for multiple products"""
        results = []
        for item in updates:
            product_id = item.get("product_id")
            if not product_id:
                continue

            update = StockUpdate(
                quantity=item.get("quantity", 0),
                operation=StockOperation(item.get("operation", "set")),
                reason=item.get("reason"),
                reference_id=item.get("reference_id")
            )

            result = await self.update_stock(product_id, update, user_id)
            if result:
                results.append(result)

        return results

    async def get_stock_level(self, store_id: str, product_id: str) -> Optional[int]:
        """Get current stock level, using cache if available"""
        # Try cache first
        try:
            cached = await RedisClient.get_cached_inventory(store_id, product_id)
            if cached is not None:
                return cached
        except Exception:
            pass

        # Fallback to database
        product = await self.products.find_one(
            {"product_id": product_id, "store_id": store_id},
            {"stock_quantity": 1}
        )

        if product:
            qty = product["stock_quantity"]
            # Update cache
            try:
                await RedisClient.cache_inventory(store_id, product_id, qty)
            except Exception:
                pass
            return qty

        return None

    async def check_availability(
        self,
        store_id: str,
        items: List[Dict]
    ) -> Dict[str, Any]:
        """Check availability of multiple products"""
        results = []
        all_available = True

        for item in items:
            product_id = item.get("product_id")
            requested_qty = item.get("quantity", 1)

            product = await self.products.find_one(
                {"product_id": product_id, "store_id": store_id},
                {"stock_quantity": 1, "name": 1, "price": 1, "is_available": 1}
            )

            if not product:
                results.append({
                    "product_id": product_id,
                    "available": False,
                    "reason": "Product not found"
                })
                all_available = False
            elif not product.get("is_available", True):
                results.append({
                    "product_id": product_id,
                    "available": False,
                    "reason": "Product not available"
                })
                all_available = False
            elif product["stock_quantity"] < requested_qty:
                results.append({
                    "product_id": product_id,
                    "available": False,
                    "stock_quantity": product["stock_quantity"],
                    "requested_quantity": requested_qty,
                    "reason": "Insufficient stock"
                })
                all_available = False
            else:
                results.append({
                    "product_id": product_id,
                    "available": True,
                    "stock_quantity": product["stock_quantity"],
                    "name": product["name"],
                    "price": product["price"]
                })

        return {
            "store_id": store_id,
            "all_available": all_available,
            "items": results
        }

    # ==================== Search & Matching ====================

    async def search_products(
        self,
        query: str,
        store_id: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 20
    ) -> List[ProductInDB]:
        """Full-text search for products"""
        search_filter = {"$text": {"$search": query}, "is_active": True}

        if store_id:
            search_filter["store_id"] = store_id
        if category:
            search_filter["category"] = category

        cursor = self.products.find(
            search_filter,
            {"score": {"$meta": "textScore"}}
        ).sort([("score", {"$meta": "textScore"})]).limit(limit)

        products = []
        async for doc in cursor:
            products.append(ProductInDB(**doc))

        return products

    async def match_smart_cart(
        self,
        store_id: str,
        items: List[Dict],
        is_demo: bool = False
    ) -> ProductMatchResponse:
        """
        Smart matching of OCR items to store inventory.
        Handles:
        1. Perfect matches
        2. Size mismatches (up-selling to next available size)
        3. Vague items (suggesting best-sellers)
        4. Unmatched/Unreadable items
        5. Synonym matching (yogurt = curd, etc.)
        """
        matched = []
        unmatched = []
        suggestions = []
        cart_total = 0.0
        
        # Synonym dictionary for common product name variations
        SYNONYMS = {
            'yogurt': ['curd', 'dahi', 'yoghurt', 'yogurt'],
            'curd': ['yogurt', 'dahi', 'yoghurt', 'curd'],
            'dahi': ['curd', 'yogurt', 'yoghurt', 'dahi'],
            'milk': ['doodh', 'dudh', 'milk'],
            'butter': ['makhan', 'butter', 'makkhan'],
            'bread': ['pav', 'bread', 'double roti'],
            'paneer': ['cottage cheese', 'paneer', 'panir'],
            'ghee': ['clarified butter', 'ghee', 'ghi'],
            'oil': ['tel', 'oil', 'cooking oil'],
            'rice': ['chawal', 'rice', 'chaawal'],
            'sugar': ['cheeni', 'sugar', 'shakkar'],
            'salt': ['namak', 'salt', 'noon'],
            'tea': ['chai', 'tea', 'chay'],
            'biscuit': ['cookie', 'biscuit', 'biskut'],
        }
        
        def get_synonyms(word):
            """Get all synonyms for a word"""
            word_lower = word.lower().strip()
            for key, synonyms in SYNONYMS.items():
                if word_lower in synonyms or word_lower == key:
                    return synonyms
            return [word_lower]

        # Get all active products for the store
        store_products = []
        async for product in self.products.find(
            {"store_id": store_id, "is_active": True, "is_available": True}
        ):
            store_products.append(product)
        
        # CRITICAL DEBUG: Check if products were loaded
        if not store_products:
            print(f"❌ AI SCAN ERROR: No products found for store {store_id} with is_active=True and is_available=True")
            print(f"   Checking without is_available filter...")
            test_count = await self.products.count_documents({"store_id": store_id, "is_active": True})
            print(f"   Products with just is_active=True: {test_count}")
        else:
            print(f"✅ AI Scan: Loaded {len(store_products)} products for {store_id}")

        for item in items:
            raw_text = item.get("raw_text", "")
            search_term = item.get("search_term_english")
            
            # 1. Handle Unreadable
            if item.get("is_unreadable", False) or not search_term:
                unmatched.append({
                    "raw_text": raw_text,
                    "reason": "unreadable",
                    "confidence": item.get("confidence_score", 0)
                })
                continue

            req_qty = float(item.get("req_qty", 1))
            req_unit = item.get("req_unit", "piece").lower()
            is_brand_specified = item.get("is_brand_specified", False)

            # --- MATCHING LOGIC ---
            
            # Helper: Get weight in grams
            def get_weight_grams(val, unit):
                unit = unit.strip().lower()
                if unit in ['kg', 'kilo']: return val * 1000
                if unit in ['g', 'gm', 'gms']: return val
                if unit in ['l', 'ltr']: return val * 1000 # Treat ml as g approx
                if unit in ['ml']: return val
                return 0

            # 1. FIND CANDIDATES (Hybrid Search: BM25 + Vector + Fuzzy)
            candidates = []
            search_synonyms = get_synonyms(search_term)
            
            print(f"🔍 Searching for '{search_term}' with synonyms: {search_synonyms}")
            
            # PRIMARY: Use HybridSearchService for intelligent matching
            try:
                from app.services.search_service import get_search_service
                hybrid_search = get_search_service()
                
                hybrid_results = hybrid_search.search(
                    query=search_term,
                    products=store_products,
                    limit=10,
                    min_score=0.4  # Increased from 0.12 to filter out poor matches
                )
                
                if hybrid_results:
                    candidates = [product for _, product in hybrid_results]
                    print(f"   🔍 Hybrid search found {len(candidates)} candidates")
                    for c in candidates[:3]:
                        print(f"   ✅ Match: '{c['name']}'")
            except Exception as e:
                print(f"   ⚠️ Hybrid search failed, using legacy: {e}")
            
            # FALLBACK: Legacy synonym + fuzzy matching
            if not candidates:
                for p in store_products:
                    product_name_lower = p["name"].lower()
                    brand_lower = (p.get("brand") or "").lower()
                    
                    if any(syn in product_name_lower for syn in search_synonyms):
                        candidates.append(p)
                        print(f"   ✅ Legacy match: '{p['name']}'")
                        continue
                    
                    product_words = product_name_lower.split()
                    for word in product_words:
                        ratio = SequenceMatcher(None, search_term.lower(), word).ratio()
                        if ratio >= 0.75:
                            candidates.append(p)
                            print(f"   ✅ Fuzzy match: '{search_term}' ~= '{word}' in '{p['name']}' ({ratio:.2f})")
                            break
                        if brand_lower:
                            brand_ratio = SequenceMatcher(None, search_term.lower(), brand_lower).ratio()
                            if brand_ratio >= 0.75:
                                candidates.append(p)
                                print(f"   ✅ Brand fuzzy: '{search_term}' ~= '{brand_lower}' ({brand_ratio:.2f})")
                                break

            
            print(f"   Found {len(candidates)} candidates")
            
            # 2. ANALYZE CANDIDATES (Ambiguity & Pack Matching)
            selected_match = None
            status = "perfect"
            reason = None
            final_qty = req_qty
            
            if len(candidates) > 1:
                # If multiple matches, check if they are distinct varieties
                # e.g. "Amul Milk" vs "Mother Dairy Milk" -> Ambiguous
                # e.g. "Dahi 200g" vs "Dahi 400g" -> Size variants (handled by weight logic)
                
                # Heuristic: If candidates differ significantly in name (brands) -> Ambiguous
                # If candidates differ mostly by weight/price -> Size variants
                
                # For this demo, let's treat generic queries as Ambiguous
                if len(candidates) > 3 or (not is_brand_specified and len(candidates) > 1):
                     # Add to AMBIGUOUS bucket for user to choose
                     # Pick the first one as "primary" but include all alternatives
                     best = candidates[0]
                     
                     # Create alternatives list with all candidate products
                     alternatives = []
                     for cand in candidates:
                         alternatives.append({
                             "product_id": cand["product_id"],
                             "name": cand["name"],
                             "brand": cand.get("brand"),
                             "price": cand["price"],
                             "mrp": cand.get("mrp", cand["price"]),
                             "unit": cand["unit"],
                             "thumbnail": cand.get("thumbnail"),
                             "stock_quantity": cand["stock_quantity"]
                         })
                     
                     matched.append(MatchedProduct(
                        product_id=best["product_id"],
                        name=best["name"],
                        brand=best.get("brand"),
                        price=best["price"],
                        mrp=best.get("mrp", best["price"]),
                        unit=best["unit"],
                        unit_value=best.get("unit_value", 1),
                        stock_quantity=best["stock_quantity"],
                        in_stock=best["stock_quantity"] > 0,
                        match_confidence=0.6,
                        original_query=raw_text,
                        search_term_english=search_term,  # Add English translation
                        matched_quantity=req_qty,
                        line_total=best["price"] * req_qty,
                        thumbnail=best.get("thumbnail"),
                        status="ambiguous",
                        modification_reason=f"Found {len(candidates)} options. Please select.",
                        alternatives=alternatives  # Add alternatives here
                    ))
                     continue
                
                # If strict brand specified, maybe filtering candidates reduced count?
                # Proceed with best candidate logic (closest weight)
            
            if candidates:
                # Find best weight match among candidates
                best_candidate = candidates[0]
                min_diff = float('inf')
                
                req_grams = get_weight_grams(req_qty, req_unit)
                
                if req_grams > 0:
                    for cand in candidates:
                        # Assuming product name has weight like "Paneer 200g" or we have metadata
                        # Mock extraction of weight from name for demo
                        import re
                        match = re.search(r'(\d+)\s*(g|gm|kg|ml|l)', cand["name"], re.IGNORECASE)
                        cand_grams = 0
                        if match:
                            val = float(match.group(1))
                            u = match.group(2)
                            cand_grams = get_weight_grams(val, u)
                        
                        if cand_grams > 0:
                            diff = abs(cand_grams - req_grams)
                            if diff < min_diff:
                                min_diff = diff
                                best_candidate = cand
                            
                            # Logic: If user wants 249g, and we have 200g and 500g.
                            # Use 500g? Or 200g? 
                            # User said: "pack of 349gm... ai should identify... suggest available option is 349gm"
                    
                    # Calculate quantity based on best candidate
                    # If user wants 249g and best is 349g -> Qty 1 (Upsize)
                    # If user wants 1kg and best is 500g -> Qty 2
                    
                    match = re.search(r'(\d+)\s*(g|gm|kg|ml|l)', best_candidate["name"], re.IGNORECASE)
                    cand_grams = 0
                    if match:
                         val = float(match.group(1))
                         u = match.group(2)
                         cand_grams = get_weight_grams(val, u)
                    
                    if cand_grams > 0:
                        if req_grams <= cand_grams:
                            final_qty = 1.0
                            if req_grams < cand_grams * 0.9: # >10% diff
                                status = "size_modified"
                                reason = f"Requested {req_qty}{req_unit}, using standard pack {cand_grams}g"
                        else:
                            # User wants more than 1 pack
                            final_qty = round(req_grams / cand_grams)
                            if final_qty == 0: final_qty = 1.0
                            status = "quantity_adjusted"
                            reason = f"Adding {final_qty} packs of {cand_grams}g to match {req_qty}{req_unit}"
                
                selected_match = best_candidate
                
                line_total = selected_match["price"] * final_qty
                cart_total += line_total

                matched.append(MatchedProduct(
                    product_id=selected_match["product_id"],
                    name=selected_match["name"],
                    brand=selected_match.get("brand"),
                    price=selected_match["price"],
                    mrp=selected_match.get("mrp", selected_match["price"]),
                    unit=selected_match["unit"],
                    unit_value=selected_match.get("unit_value", 1),
                    stock_quantity=selected_match["stock_quantity"],
                    in_stock=selected_match["stock_quantity"] > 0,
                    match_confidence=item.get("confidence_score", 0.9),
                    original_query=raw_text,
                    search_term_english=search_term,  # Add English translation
                    matched_quantity=final_qty,
                    line_total=line_total,
                    thumbnail=selected_match.get("thumbnail"),
                    status=status,
                    modification_reason=reason
                ))
                continue

            # Attempt 2: Suggestions (Category Match)
            category_match = None
            keywords = search_term.split()
            valid_suggestions = []
            
            for p in store_products:
                if any(k.lower() in p.get("category", "").lower() for k in keywords):
                    valid_suggestions.append(p)
            
            # If we found suggestions, add to suggestions list, NOT matched list
            # User wants "Select dairy one"
            if valid_suggestions:
                 # Add to unmatched but with specific suggestions
                 suggestions.append({
                     "original_query": raw_text,
                     "suggestions": [
                         {
                             "product_id": p["product_id"],
                             "name": p["name"],
                             "price": p["price"],
                             "thumbnail": p.get("thumbnail")
                         } for p in valid_suggestions[:3]
                     ],
                     "reason": "category_match"
                 })
                 
                 # Also Add to unmatched list so it appears in "Needs Help" but with suggestions?
                 # No, structured response has separate `suggestions` field.
                 # Frontend should merge them.
                 
                 # Actually, let's put it in `unmatched` with a special flag/data
                 unmatched.append({
                    "raw_text": raw_text,
                    "reason": "ambiguous_category",
                    "search_term": search_term,
                    "suggested_products": [p["product_id"] for p in valid_suggestions[:3]] # lightweight
                 })
                 continue

            # Attempt 3: Cross-store search (search other stores)
            # Use is_demo flag to determine which stores to search
            cross_store_candidates = []
            if is_demo:
                # Demo mode: only search other demo stores
                demo_stores = ['DEMO_STORE_1', 'DEMO_STORE_2', 'DEMO_STORE_3']
                other_demo_stores = [s for s in demo_stores if s != store_id]
                cross_store_query = {"store_id": {"$in": other_demo_stores}, "is_active": True, "is_available": True}
            else:
                # Real mode: search only real stores (exclude demo stores)
                cross_store_query = {
                    "store_id": {"$ne": store_id},
                    "is_active": True,
                    "is_available": True,
                    "$or": [
                        {"is_demo": {"$exists": False}},
                        {"is_demo": False}
                    ]
                }
            
            
            cross_store_products = []
            async for p in self.products.find(cross_store_query):
                cross_store_products.append(p)
            
            # PRIMARY: Hybrid search for cross-store
            try:
                from app.services.search_service import get_search_service
                hybrid_search = get_search_service()
                cross_results = hybrid_search.search(
                    query=search_term,
                    products=cross_store_products,
                    limit=5,
                    min_score=0.4  # Match current store threshold to filter poor matches
                )
                if cross_results:
                    cross_store_candidates = [p for _, p in cross_results]
                    print(f"   🔍 Cross-store hybrid search found {len(cross_store_candidates)} candidates")
                    for c in cross_store_candidates[:3]:
                        print(f"   ✅ Cross-store match: '{c['name']}' in {c.get('store_id', 'unknown')}")
            except Exception as e:
                print(f"   ⚠️ Cross-store hybrid search failed: {e}")
            
            # FALLBACK: Legacy matching for cross-store
            if not cross_store_candidates:
                for p in cross_store_products:
                    product_name_lower = p["name"].lower()
                    if any(syn in product_name_lower for syn in search_synonyms):
                        cross_store_candidates.append(p)
            
            if cross_store_candidates:
                # Get store names for cross-store matches
                # Demo store name fallback (demo stores may not have DB entries)
                demo_store_names = {
                    'DEMO_STORE_1': 'TestShop 1 - Kirana Corner',
                    'DEMO_STORE_2': 'TestShop 2 - Daily Needs',
                    'DEMO_STORE_3': 'TestShop 3 - Fresh Mart',
                }
                store_names = {}
                for cand in cross_store_candidates:
                    sid = cand.get("store_id", "")
                    if sid and sid not in store_names:
                        if sid in demo_store_names:
                            store_names[sid] = demo_store_names[sid]
                        else:
                            store_doc = await self.stores.find_one({"store_id": sid}, {"business_name": 1, "name": 1})
                            store_names[sid] = store_doc.get("business_name") or store_doc.get("name", sid) if store_doc else sid
                
                # Pick best candidate from other stores
                best_cross = cross_store_candidates[0]
                cross_sid = best_cross.get("store_id", "")
                
                # Build alternatives from cross-store candidates
                cross_alternatives = []
                for cand in cross_store_candidates[:5]:
                    csid = cand.get("store_id", "")
                    cross_alternatives.append({
                        "product_id": cand["product_id"],
                        "name": cand["name"],
                        "brand": cand.get("brand"),
                        "price": cand["price"],
                        "mrp": cand.get("mrp", cand["price"]),
                        "unit": cand["unit"],
                        "thumbnail": cand.get("thumbnail"),
                        "stock_quantity": cand["stock_quantity"],
                        "store_id": csid,
                        "store_name": store_names.get(csid, csid),
                    })
                
                matched.append(MatchedProduct(
                    product_id=best_cross["product_id"],
                    name=best_cross["name"],
                    brand=best_cross.get("brand"),
                    price=best_cross["price"],
                    mrp=best_cross.get("mrp", best_cross["price"]),
                    unit=best_cross["unit"],
                    unit_value=best_cross.get("unit_value", 1),
                    stock_quantity=best_cross["stock_quantity"],
                    in_stock=best_cross["stock_quantity"] > 0,
                    match_confidence=0.5,
                    original_query=raw_text,
                    search_term_english=search_term,
                    matched_quantity=req_qty,
                    line_total=best_cross["price"] * req_qty,
                    thumbnail=best_cross.get("thumbnail"),
                    status="cross_store",
                    modification_reason=f"Not available in your shop. Found in {store_names.get(cross_sid, 'another shop')}.",
                    alternatives=cross_alternatives,
                    is_cross_store=True,
                    source_store_id=cross_sid,
                    source_store_name=store_names.get(cross_sid, "Another Shop"),
                ))
                continue

            # If completely unmatched
            unmatched.append({
                "raw_text": raw_text,
                "reason": "not_found",
                "search_term": search_term
            })

        return ProductMatchResponse(
            store_id=store_id,
            matched=matched,
            unmatched=unmatched,
            suggestions=suggestions,
            cart_total=round(cart_total, 2)
        )

    # ==================== Inventory Analytics ====================

    async def get_inventory_summary(self, store_id: str) -> InventorySummary:
        """Get inventory summary with alerts"""
        # Aggregation pipeline for summary
        pipeline = [
            {"$match": {"store_id": store_id, "is_active": True}},
            {"$group": {
                "_id": None,
                "total_products": {"$sum": 1},
                "active_products": {
                    "$sum": {"$cond": ["$is_available", 1, 0]}
                },
                "out_of_stock": {
                    "$sum": {"$cond": [{"$eq": ["$stock_quantity", 0]}, 1, 0]}
                },
                "low_stock": {
                    "$sum": {
                        "$cond": [
                            {"$and": [
                                {"$gt": ["$stock_quantity", 0]},
                                {"$lte": ["$stock_quantity", "$reorder_threshold"]}
                            ]},
                            1, 0
                        ]
                    }
                },
                "total_value": {
                    "$sum": {"$multiply": ["$stock_quantity", "$price"]}
                }
            }}
        ]

        result = await self.products.aggregate(pipeline).to_list(1)
        summary_data = result[0] if result else {}

        # Get alerts
        alerts = await self._get_inventory_alerts(store_id)

        return InventorySummary(
            store_id=store_id,
            total_products=summary_data.get("total_products", 0),
            active_products=summary_data.get("active_products", 0),
            out_of_stock_count=summary_data.get("out_of_stock", 0),
            low_stock_count=summary_data.get("low_stock", 0),
            total_inventory_value=round(summary_data.get("total_value", 0), 2),
            alerts=alerts
        )

    async def get_low_stock_products(self, store_id: str) -> List[ProductInDB]:
        """Get products that are low on stock"""
        cursor = self.products.find({
            "store_id": store_id,
            "is_active": True,
            "$expr": {
                "$and": [
                    {"$gt": ["$stock_quantity", 0]},
                    {"$lte": ["$stock_quantity", "$reorder_threshold"]}
                ]
            }
        }).sort("stock_quantity", 1)

        products = []
        async for doc in cursor:
            products.append(ProductInDB(**doc))
        return products

    async def get_out_of_stock_products(self, store_id: str) -> List[ProductInDB]:
        """Get products that are out of stock"""
        cursor = self.products.find({
            "store_id": store_id,
            "is_active": True,
            "stock_quantity": 0
        })

        products = []
        async for doc in cursor:
            products.append(ProductInDB(**doc))
        return products

    # ==================== Helper Methods ====================

    def _get_movement_type(self, operation: StockOperation) -> StockMovementType:
        """Map stock operation to movement type"""
        mapping = {
            StockOperation.SET: StockMovementType.ADJUSTMENT,
            StockOperation.ADD: StockMovementType.PROCUREMENT,
            StockOperation.SUBTRACT: StockMovementType.SALE,
            StockOperation.RESERVE: StockMovementType.SALE,
            StockOperation.RELEASE: StockMovementType.RETURN
        }
        return mapping.get(operation, StockMovementType.ADJUSTMENT)

    def _calculate_match_score(
        self,
        query: str,
        product_name: str,
        tags: List[str],
        brand: str,
        category: str
    ) -> float:
        """Calculate similarity score between query and product"""
        query_lower = query.lower()
        name_lower = product_name.lower()

        # Exact match in name
        if query_lower == name_lower:
            return 1.0

        # Query contained in name
        if query_lower in name_lower:
            return 0.9

        # Name contained in query
        if name_lower in query_lower:
            return 0.85

        # Check tags
        for tag in tags:
            if query_lower == tag or query_lower in tag:
                return 0.8

        # Check brand
        if brand and query_lower in brand.lower():
            return 0.75

        # Fuzzy matching
        ratio = SequenceMatcher(None, query_lower, name_lower).ratio()
        if ratio > 0.6:
            return ratio * 0.8

        # Check individual words
        query_words = set(query_lower.split())
        name_words = set(name_lower.split())
        common_words = query_words & name_words
        if common_words:
            return 0.5 + (len(common_words) / max(len(query_words), len(name_words))) * 0.3

        return 0.0

    async def _get_inventory_alerts(self, store_id: str) -> List[InventoryAlert]:
        """Get inventory alerts for a store"""
        alerts = []

        # Out of stock alerts
        async for product in self.products.find({
            "store_id": store_id,
            "is_active": True,
            "stock_quantity": 0
        }):
            alerts.append(InventoryAlert(
                product_id=product["product_id"],
                product_name=product["name"],
                current_stock=0,
                reorder_threshold=product.get("reorder_threshold", 10),
                alert_type="out_of_stock"
            ))

        # Low stock alerts
        async for product in self.products.find({
            "store_id": store_id,
            "is_active": True,
            "$expr": {
                "$and": [
                    {"$gt": ["$stock_quantity", 0]},
                    {"$lte": ["$stock_quantity", "$reorder_threshold"]}
                ]
            }
        }):
            alerts.append(InventoryAlert(
                product_id=product["product_id"],
                product_name=product["name"],
                current_stock=product["stock_quantity"],
                reorder_threshold=product.get("reorder_threshold", 10),
                alert_type="low_stock"
            ))

        return alerts

    async def _get_category_suggestions(
        self,
        store_id: str,
        query: str,
        store_products: List[Dict]
    ) -> List[Dict]:
        """Get product suggestions based on category inference"""
        suggestions = []
        query_lower = query.lower()

        # Simple category inference
        category_keywords = {
            "rice": "Groceries",
            "dal": "Groceries",
            "milk": "Dairy",
            "bread": "Bakery",
            "oil": "Groceries",
            "sugar": "Groceries",
            "salt": "Groceries",
            "soap": "Personal Care",
            "shampoo": "Personal Care"
        }

        inferred_category = None
        for keyword, category in category_keywords.items():
            if keyword in query_lower:
                inferred_category = category
                break

        if inferred_category:
            for product in store_products:
                if product.get("category") == inferred_category and product["stock_quantity"] > 0:
                    suggestions.append({
                        "product_id": product["product_id"],
                        "name": product["name"],
                        "price": product["price"]
                    })
                    if len(suggestions) >= 3:
                        break

        return suggestions
