"""
Voice Context Service
Pre-loads and caches all necessary data for voice conversations in Redis
Optimizes performance by avoiding repeated database calls during conversation
"""
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from bson import ObjectId

from app.db.redis import RedisClient
from app.db.mongodb import get_database

logger = logging.getLogger(__name__)

class VoiceContextService:
    """
    Manages conversation context data in Redis for fast AI access
    Pre-loads nearby stores, inventory, and user data when session starts
    """
    
    def __init__(self):
        self.redis = RedisClient
        self.db = None  # Will be initialized on first use
        self.context_ttl = 1800  # 30 minutes
    
    async def _get_db(self):
        """Get database connection (lazy initialization)"""
        if self.db is None:
            self.db = await get_database()
        return self.db
    
    async def initialize_customer_context(
        self,
        session_id: str,
        user_id: str,
        latitude: float,
        longitude: float,
        radius_km: float = 5.0
    ) -> Dict:
        """
        Pre-load all data needed for customer voice shopping
        Stores in Redis for fast AI access during conversation
        
        Returns context summary for AI
        """
        logger.info(f"Initializing customer context for session {session_id}")
        
        context = {
            "session_id": session_id,
            "user_id": user_id,
            "location": {"lat": latitude, "lon": longitude},
            "initialized_at": datetime.now().isoformat(),
            "nearby_stores": [],
            "available_products": [],
            "product_index": {},  # Fast lookup by name
            "brand_index": {},  # Fast lookup by brand
            "category_index": {}  # Fast lookup by category
        }
        
        # 1. Find nearby stores
        nearby_stores = await self._find_nearby_stores(latitude, longitude, radius_km)
        context["nearby_stores"] = nearby_stores
        logger.info(f"Found {len(nearby_stores)} nearby stores")
        
        # 2. Load inventory from all nearby stores
        all_products = []
        for store in nearby_stores:
            store_products = await self._load_store_inventory(store['id'])
            all_products.extend(store_products)
        
        # 3. Deduplicate and enrich products
        unique_products = self._deduplicate_products(all_products)
        context["available_products"] = unique_products
        logger.info(f"Loaded {len(unique_products)} unique products")
        
        # 4. Build search indexes for fast lookup
        context["product_index"] = self._build_product_index(unique_products)
        context["brand_index"] = self._build_brand_index(unique_products)
        context["category_index"] = self._build_category_index(unique_products)
        
        # 5. Load user preferences and history
        user_data = await self._load_user_data(user_id)
        context["user_preferences"] = user_data.get("preferences", {})
        context["purchase_history"] = user_data.get("recent_purchases", [])
        
        # 6. Store in Redis with TTL
        await self._store_context_in_redis(session_id, context)
        
        # 7. Return summary for AI
        return {
            "stores_count": len(nearby_stores),
            "products_count": len(unique_products),
            "categories": list(context["category_index"].keys()),
            "top_brands": list(context["brand_index"].keys())[:20],
            "user_favorites": user_data.get("favorites", [])
        }
    
    async def initialize_from_app_data(
        self,
        session_id: str,
        user_id: str,
        latitude: float,
        longitude: float,
        stores_data: List[Dict]
    ) -> Dict:
        """
        Initialize context from data already loaded by Flutter app
        NO API CALLS - uses data sent from app
        Optimized for zero backend calls
        
        Returns context summary for AI
        """
        logger.info(f"Initializing context from app data for session {session_id}")
        
        context = {
            "session_id": session_id,
            "user_id": user_id,
            "location": {"lat": latitude, "lon": longitude},
            "initialized_at": datetime.now().isoformat(),
            "nearby_stores": [],
            "available_products": [],
            "product_index": {},
            "brand_index": {},
            "category_index": {}
        }
        
        # 1. Process stores data from app
        nearby_stores = []
        all_products = []
        
        for store_data in stores_data:
            store_info = {
                "id": store_data.get('id'),
                "name": store_data.get('name'),
                "distance_km": store_data.get('distance', 0),
                "rating": store_data.get('rating', 4.0)
            }
            nearby_stores.append(store_info)
            
            # Extract products from store data if available
            if 'products' in store_data:
                for p in store_data['products']:
                    weight_in_grams = self._parse_weight(p.get('weight', p.get('unit', '1 piece')))
                    price_per_100g = (p['price'] / weight_in_grams * 100) if weight_in_grams > 0 else 0
                    
                    all_products.append({
                        "id": p.get('id'),
                        "store_id": store_data.get('id'),
                        "name": p.get('name'),
                        "brand": p.get('brand', 'Local'),
                        "category": p.get('category', 'General'),
                        "price": p.get('price', 0),
                        "weight": p.get('weight', p.get('unit', '1 piece')),
                        "weight_grams": weight_in_grams,
                        "price_per_100g": round(price_per_100g, 2),
                        "stock": p.get('stock', 0),
                        "quality_rating": p.get('quality_rating', 4.0),
                        "benefits": p.get('benefits', []),
                        "drawbacks": p.get('drawbacks', []),
                        "description": p.get('description', ''),
                        "is_premium": p.get('brand', 'Local') in ['Tata', 'Amul', 'Britannia', 'Nestle', 'ITC', 'Parle'],
                        "tags": p.get('tags', [])
                    })
        
        context["nearby_stores"] = nearby_stores
        logger.info(f"Loaded {len(nearby_stores)} stores from app data")
        
        # 2. Deduplicate products
        unique_products = self._deduplicate_products(all_products)
        context["available_products"] = unique_products
        logger.info(f"Processed {len(unique_products)} unique products from app data")
        
        # 3. Build search indexes
        context["product_index"] = self._build_product_index(unique_products)
        context["brand_index"] = self._build_brand_index(unique_products)
        context["category_index"] = self._build_category_index(unique_products)
        
        # 4. Store in Redis with TTL
        await self._store_context_in_redis(session_id, context)
        
        # 5. Return summary
        return {
            "stores_count": len(nearby_stores),
            "products_count": len(unique_products),
            "categories": list(context["category_index"].keys()),
            "top_brands": list(context["brand_index"].keys())[:20]
        }
    
    async def initialize_store_context(
        self,
        session_id: str,
        store_id: str
    ) -> Dict:
        """
        Pre-load all data needed for store owner voice management
        Stores in Redis for fast AI access during conversation
        
        Returns context summary for AI
        """
        logger.info(f"Initializing store context for session {session_id}")
        
        context = {
            "session_id": session_id,
            "store_id": store_id,
            "initialized_at": datetime.now().isoformat(),
            "store_info": {},
            "inventory": [],
            "sales_data": {},
            "analytics": {}
        }
        
        # 1. Load store information
        db = await self._get_db()
        store = await db.stores.find_one({"_id": ObjectId(store_id)})
        if store:
            context["store_info"] = {
                "id": str(store["_id"]),
                "name": store.get("name"),
                "location": store.get("location"),
                "owner": store.get("owner_name")
            }
        
        # 2. Load complete inventory
        inventory = await self._load_store_inventory(store_id)
        context["inventory"] = inventory
        logger.info(f"Loaded {len(inventory)} products for store")
        
        # 3. Load today's sales data
        sales_data = await self._load_sales_data(store_id)
        context["sales_data"] = sales_data
        
        # 4. Calculate analytics
        analytics = await self._calculate_store_analytics(store_id, inventory, sales_data)
        context["analytics"] = analytics
        
        # 5. Store in Redis with TTL
        await self._store_context_in_redis(session_id, context)
        
        # 6. Return summary for AI
        return {
            "store_name": context["store_info"].get("name"),
            "total_products": len(inventory),
            "low_stock_count": analytics.get("low_stock_count", 0),
            "today_revenue": sales_data.get("total_revenue", 0),
            "today_orders": sales_data.get("total_orders", 0),
            "top_selling": analytics.get("top_products", [])[:5]
        }
    
    async def get_context(self, session_id: str) -> Optional[Dict]:
        """Retrieve cached context from Redis"""
        key = f"voice_context:{session_id}"
        data = await self.redis.get(key)
        if data:
            return json.loads(data)
        return None
    
    async def search_products(
        self,
        session_id: str,
        query: str,
        filters: Optional[Dict] = None
    ) -> List[Dict]:
        """
        Fast product search using cached context
        No database calls - uses Redis data only
        """
        context = await self.get_context(session_id)
        if not context:
            logger.warning(f"No context found for session {session_id}")
            return []
        
        products = context.get("available_products", [])
        product_index = context.get("product_index", {})
        
        # Search in index first (fastest)
        query_lower = query.lower()
        if query_lower in product_index:
            product_ids = product_index[query_lower]
            results = [p for p in products if p['id'] in product_ids]
        else:
            # Fallback to fuzzy search
            results = [
                p for p in products
                if query_lower in p['name'].lower() or
                   query_lower in p.get('brand', '').lower() or
                   query_lower in p.get('category', '').lower()
            ]
        
        # Apply filters if provided
        if filters:
            if 'brand' in filters:
                results = [p for p in results if p.get('brand') == filters['brand']]
            if 'max_price' in filters:
                results = [p for p in results if p['price'] <= filters['max_price']]
            if 'in_stock' in filters and filters['in_stock']:
                results = [p for p in results if p.get('stock', 0) > 0]
        
        # Sort by relevance and stock
        results.sort(key=lambda x: (x.get('stock', 0) == 0, -x.get('quality_rating', 4.0)))
        
        return results[:20]  # Top 20 results
    
    async def get_product_details(self, session_id: str, product_id: str) -> Optional[Dict]:
        """Get detailed product info from cached context"""
        context = await self.get_context(session_id)
        if not context:
            return None
        
        products = context.get("available_products", [])
        for product in products:
            if product['id'] == product_id:
                return product
        return None
    
    async def update_cart(self, session_id: str, cart_data: Dict) -> bool:
        """Update cart in Redis"""
        key = f"voice_cart:{session_id}"
        await self.redis.setex(key, self.context_ttl, json.dumps(cart_data))
        return True
    
    async def get_cart(self, session_id: str) -> Optional[Dict]:
        """Get cart from Redis"""
        key = f"voice_cart:{session_id}"
        data = await self.redis.get(key)
        if data:
            return json.loads(data)
        return {"items": [], "total": 0}
    
    async def cleanup_context(self, session_id: str):
        """Clean up context when session ends"""
        keys = [
            f"voice_context:{session_id}",
            f"voice_cart:{session_id}"
        ]
        for key in keys:
            await self.redis.delete(key)
        logger.info(f"Cleaned up context for session {session_id}")
    
    # ==================== Private Helper Methods ====================
    
    async def _find_nearby_stores(
        self,
        latitude: float,
        longitude: float,
        radius_km: float
    ) -> List[Dict]:
        """Find stores within radius"""
        # MongoDB geospatial query
        db = await self._get_db()
        stores = await db.stores.find({
            "location": {
                "$near": {
                    "$geometry": {
                        "type": "Point",
                        "coordinates": [longitude, latitude]
                    },
                    "$maxDistance": radius_km * 1000  # Convert to meters
                }
            },
            "is_active": True
        }).limit(10).to_list(length=10)
        
        return [
            {
                "id": str(store["_id"]),
                "name": store.get("name"),
                "distance_km": self._calculate_distance(
                    latitude, longitude,
                    store["location"]["coordinates"][1],
                    store["location"]["coordinates"][0]
                ),
                "rating": store.get("rating", 4.0)
            }
            for store in stores
        ]
    
    async def _load_store_inventory(self, store_id: str) -> List[Dict]:
        """Load all products from a store"""
        db = await self._get_db()
        products = await db.products.find({
            "store_id": store_id,
            "is_active": True
        }).to_list(length=1000)
        
        enriched_products = []
        for p in products:
            weight_in_grams = self._parse_weight(p.get('weight', p.get('unit', '1 piece')))
            price_per_100g = (p['price'] / weight_in_grams * 100) if weight_in_grams > 0 else 0
            
            enriched_products.append({
                "id": str(p['_id']),
                "store_id": store_id,
                "name": p['name'],
                "brand": p.get('brand', 'Local'),
                "category": p.get('category', 'General'),
                "price": p['price'],
                "weight": p.get('weight', p.get('unit', '1 piece')),
                "weight_grams": weight_in_grams,
                "price_per_100g": round(price_per_100g, 2),
                "stock": p.get('stock', 0),
                "quality_rating": p.get('quality_rating', 4.0),
                "benefits": p.get('benefits', []),
                "drawbacks": p.get('drawbacks', []),
                "description": p.get('description', ''),
                "is_premium": p.get('brand', 'Local') in ['Tata', 'Amul', 'Britannia', 'Nestle', 'ITC', 'Parle'],
                "tags": p.get('tags', [])
            })
        
        return enriched_products
    
    def _deduplicate_products(self, products: List[Dict]) -> List[Dict]:
        """Remove duplicate products, keeping best price/rating"""
        unique = {}
        
        for product in products:
            key = f"{product['name']}_{product['brand']}_{product['weight']}"
            
            if key not in unique:
                unique[key] = product
            else:
                # Keep product with better price or higher stock
                existing = unique[key]
                if product['price'] < existing['price'] or product['stock'] > existing['stock']:
                    unique[key] = product
        
        return list(unique.values())
    
    def _build_product_index(self, products: List[Dict]) -> Dict[str, List[str]]:
        """Build search index by product name keywords"""
        index = {}
        
        for product in products:
            # Index by full name
            name_lower = product['name'].lower()
            if name_lower not in index:
                index[name_lower] = []
            index[name_lower].append(product['id'])
            
            # Index by keywords
            keywords = name_lower.split()
            for keyword in keywords:
                if len(keyword) > 2:  # Skip very short words
                    if keyword not in index:
                        index[keyword] = []
                    if product['id'] not in index[keyword]:
                        index[keyword].append(product['id'])
        
        return index
    
    def _build_brand_index(self, products: List[Dict]) -> Dict[str, List[str]]:
        """Build index by brand"""
        index = {}
        
        for product in products:
            brand = product.get('brand', 'Local').lower()
            if brand not in index:
                index[brand] = []
            index[brand].append(product['id'])
        
        return index
    
    def _build_category_index(self, products: List[Dict]) -> Dict[str, List[str]]:
        """Build index by category"""
        index = {}
        
        for product in products:
            category = product.get('category', 'General').lower()
            if category not in index:
                index[category] = []
            index[category].append(product['id'])
        
        return index
    
    async def _load_user_data(self, user_id: str) -> Dict:
        """Load user preferences and history"""
        db = await self._get_db()
        
        # Try to find user by string ID or ObjectId
        try:
            if len(user_id) == 24:  # Might be ObjectId
                user = await db.users.find_one({"_id": ObjectId(user_id)})
            else:
                user = await db.users.find_one({"user_id": user_id})
        except:
            # If user not found, return empty data
            return {}
            
        if not user:
            return {}
        
        # Get recent purchases
        recent_orders = await db.orders.find({
            "user_id": user_id,
            "status": "completed"
        }).sort("created_at", -1).limit(10).to_list(length=10)
        
        recent_purchases = []
        for order in recent_orders:
            for item in order.get('items', []):
                recent_purchases.append(item['product_id'])
        
        return {
            "preferences": user.get("preferences", {}),
            "favorites": user.get("favorite_products", []),
            "recent_purchases": recent_purchases
        }
    
    async def _load_sales_data(self, store_id: str) -> Dict:
        """Load today's sales data for store"""
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)
        
        db = await self._get_db()
        orders = await db.orders.find({
            "store_id": store_id,
            "created_at": {"$gte": today, "$lt": tomorrow},
            "status": {"$in": ["completed", "delivered"]}
        }).to_list(length=1000)
        
        total_revenue = sum(order.get('total_amount', 0) for order in orders)
        
        # Count products sold
        product_sales = {}
        for order in orders:
            for item in order.get('items', []):
                pid = item['product_id']
                product_sales[pid] = product_sales.get(pid, 0) + item['quantity']
        
        return {
            "total_revenue": total_revenue,
            "total_orders": len(orders),
            "average_order_value": total_revenue / len(orders) if orders else 0,
            "product_sales": product_sales
        }
    
    async def _calculate_store_analytics(
        self,
        store_id: str,
        inventory: List[Dict],
        sales_data: Dict
    ) -> Dict:
        """Calculate analytics for store"""
        # Low stock items
        low_stock = [p for p in inventory if p.get('stock', 0) <= 10]
        
        # Top selling products
        product_sales = sales_data.get('product_sales', {})
        top_products = sorted(
            product_sales.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        # Get product names for top sellers
        top_products_with_names = []
        for product_id, quantity in top_products:
            product = next((p for p in inventory if p['id'] == product_id), None)
            if product:
                top_products_with_names.append({
                    "name": product['name'],
                    "quantity_sold": quantity,
                    "revenue": quantity * product['price']
                })
        
        return {
            "low_stock_count": len(low_stock),
            "low_stock_items": [{"name": p['name'], "stock": p['stock']} for p in low_stock[:10]],
            "top_products": top_products_with_names,
            "total_inventory_value": sum(p['price'] * p.get('stock', 0) for p in inventory)
        }
    
    async def _store_context_in_redis(self, session_id: str, context: Dict):
        """Store context in Redis with TTL"""
        key = f"voice_context:{session_id}"
        await self.redis.setex(key, self.context_ttl, json.dumps(context, default=str))
        logger.info(f"Stored context in Redis for session {session_id}")
    
    def _calculate_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two points in km"""
        from math import radians, sin, cos, sqrt, atan2
        
        R = 6371  # Earth radius in km
        
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))
        
        return R * c
    
    def _parse_weight(self, weight_str: str) -> float:
        """Parse weight string to grams"""
        import re
        
        if not weight_str or weight_str == 'piece':
            return 1.0
        
        match = re.match(r'([\d.]+)\s*(kg|gm|g|l|ml|piece)?', str(weight_str).lower())
        if not match:
            return 1.0
        
        value = float(match.group(1))
        unit = match.group(2) or 'piece'
        
        if unit in ['kg', 'l']:
            return value * 1000
        elif unit in ['gm', 'g', 'ml']:
            return value
        else:
            return value
