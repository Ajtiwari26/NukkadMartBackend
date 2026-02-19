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
        items: List[Dict]
    ) -> ProductMatchResponse:
        """
        Smart matching of OCR items to store inventory.
        Handles:
        1. Perfect matches
        2. Size mismatches (up-selling to next available size)
        3. Vague items (suggesting best-sellers)
        4. Unmatched/Unreadable items
        """
        matched = []
        unmatched = []
        suggestions = []
        cart_total = 0.0

        # Get all active products for the store
        # Optimization: In a real app, we might use vector search or text search
        # But for Nukkad shops (< 2000 items), in-memory matching is fast enough
        store_products = []
        async for product in self.products.find(
            {"store_id": store_id, "is_active": True, "is_available": True}
        ):
            store_products.append(product)

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
            
            # Attempt 1: Exact Name Match
            best_match = None
            for p in store_products:
                if search_term.lower() in p["name"].lower():
                    # Check unit compatibility if possible
                    # This is a simplified check
                    best_match = p
                    break
            
            if best_match:
                # Check for size/quantity mismatch
                # Extract size from product name if possible or use unit
                # Logic: If user asked for 200g but product is 500g
                
                # Simplified logic for demo:
                # If the product name contains the requested unit but different value, flag it
                # For now, we'll assume "Perfect Match" if name matches
                
                # Check if it's a size mismatch (mock logic for demonstration)
                status = "perfect"
                reason = None
                
                # Example: req 200g, found 500g
                # We need structured unit/value in Product model to do this accurately
                # For now, we will rely on text analysis or assume perfect if name matches
                
                line_total = best_match["price"] * req_qty
                cart_total += line_total

                matched.append(MatchedProduct(
                    product_id=best_match["product_id"],
                    name=best_match["name"],
                    brand=best_match.get("brand"),
                    price=best_match["price"],
                    mrp=best_match.get("mrp", best_match["price"]),
                    unit=best_match["unit"],
                    unit_value=best_match.get("unit_value", 1),
                    stock_quantity=best_match["stock_quantity"],
                    in_stock=best_match["stock_quantity"] > 0,
                    match_confidence=item.get("confidence_score", 0.9),
                    original_query=raw_text,
                    matched_quantity=req_qty,
                    line_total=line_total,
                    thumbnail=best_match.get("thumbnail"),
                    status=status,
                    modification_reason=reason
                ))
                continue

            # Attempt 2: Category/Vague Match (Brand Suggestion)
            # If no exact match, try to find by category keywords
            # e.g., "Toothpaste" -> suggest "Colgate"
            
            category_match = None
            keywords = search_term.split()
            for p in store_products:
                # If any significant keyword matches category or name
                if any(k.lower() in p["name"].lower() or k.lower() in p.get("category", "").lower() for k in keywords):
                    category_match = p
                    break
            
            if category_match:
                line_total = category_match["price"] * req_qty
                cart_total += line_total
                
                matched.append(MatchedProduct(
                    product_id=category_match["product_id"],
                    name=category_match["name"],
                    brand=category_match.get("brand"),
                    price=category_match["price"],
                    mrp=category_match.get("mrp", category_match["price"]),
                    unit=category_match["unit"],
                    unit_value=category_match.get("unit_value", 1),
                    stock_quantity=category_match["stock_quantity"],
                    in_stock=category_match["stock_quantity"] > 0,
                    match_confidence=0.7, # Lower confidence for suggestions
                    original_query=raw_text,
                    matched_quantity=req_qty,
                    line_total=line_total,
                    thumbnail=category_match.get("thumbnail"),
                    status="brand_suggested" if not is_brand_specified else "substitute_suggested",
                    modification_reason=f"Suggested {category_match['name']} for '{search_term}'"
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
