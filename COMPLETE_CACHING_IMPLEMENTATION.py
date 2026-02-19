"""
Complete Backend Caching Implementation
Add this code to respective router files
"""

# ============================================
# 1. STORES ROUTER - Store Details
# File: backend/app/routers/stores.py
# ============================================

# Add after nearby stores endpoint:

@router.get("/{store_id}")
async def get_store(store_id: str):
    """Get store details by ID with caching."""
    cache_key = f"store:{store_id}"
    
    # Check cache
    cached_data = cache.get(cache_key)
    if cached_data:
        print(f"✓ Cache hit: {cache_key}")
        return cached_data
    
    print(f"✗ Cache miss: {cache_key}")
    
    # Fetch from DB
    db = await get_database()
    store = await db.stores.find_one({"store_id": store_id})
    
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    # Remove MongoDB _id
    store.pop("_id", None)
    
    # Cache result
    cache.set(cache_key, store, TTL_STORE_INFO)
    print(f"✓ Cached: {cache_key} for {TTL_STORE_INFO}s")
    
    return store


# ============================================
# 2. INVENTORY ROUTER - Products List
# File: backend/app/routers/inventory.py
# ============================================

# Update list_store_products function:

@router.get("/stores/{store_id}/products", response_model=ProductListResponse)
async def list_store_products(
    store_id: str,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    in_stock_only: bool = False,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("name", regex="^(name|price|stock_quantity|created_at)$"),
    sort_order: str = Query("asc", regex="^(asc|desc)$"),
    service: InventoryService = Depends(get_inventory_service)
):
    """List all products for a specific store with caching."""
    
    # Build cache key from parameters
    cache_key = f"inventory:{store_id}:products:{category}:{subcategory}:{in_stock_only}:{search}:{page}:{page_size}:{sort_by}:{sort_order}"
    
    # Check cache
    cached_data = cache.get(cache_key)
    if cached_data:
        print(f"✓ Cache hit: {cache_key}")
        return cached_data
    
    print(f"✗ Cache miss: {cache_key}")
    
    # Fetch from service
    result = await service.list_products(
        store_id=store_id,
        category=category,
        subcategory=subcategory,
        in_stock_only=in_stock_only,
        search_query=search,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=1 if sort_order == "asc" else -1
    )

    response = ProductListResponse(
        products=[ProductResponse(**p.model_dump()) for p in result["products"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        total_pages=result["total_pages"]
    )
    
    # Cache result
    response_dict = response.dict()
    cache.set(cache_key, response_dict, TTL_INVENTORY_LIST)
    print(f"✓ Cached: {cache_key} for {TTL_INVENTORY_LIST}s")
    
    return response


# ============================================
# 3. ORDERS ROUTER - User Orders
# File: backend/app/routers/orders.py
# ============================================

# Add imports at top:
from app.core.cache import cache, TTL_USER_ORDERS, TTL_STORE_ORDERS

# Update get_user_orders function:

@router.get("/user/{user_id}")
async def get_user_orders(
    user_id: str,
    status: Optional[OrderStatus] = None,
    limit: int = Query(20, ge=1, le=100)
):
    """Get user orders with caching."""
    cache_key = f"orders:user:{user_id}:{status}:{limit}"
    
    # Check cache
    cached_data = cache.get(cache_key)
    if cached_data:
        print(f"✓ Cache hit: {cache_key}")
        return cached_data
    
    print(f"✗ Cache miss: {cache_key}")
    
    # Fetch from DB
    db = await get_database()
    query = {"user_id": user_id}
    if status:
        query["status"] = status
    
    orders = await db.orders.find(query).sort("created_at", -1).limit(limit).to_list(limit)
    
    # Remove MongoDB _id
    for order in orders:
        order.pop("_id", None)
    
    # Cache result
    cache.set(cache_key, orders, TTL_USER_ORDERS)
    print(f"✓ Cached: {cache_key} for {TTL_USER_ORDERS}s")
    
    return orders


# ============================================
# 4. USERS ROUTER - User Profile
# File: backend/app/routers/users.py
# ============================================

# Add imports at top:
from app.core.cache import cache, TTL_STORE_INFO

# Add caching to get_user endpoint:

@router.get("/{user_id}")
async def get_user(user_id: str):
    """Get user profile with caching."""
    cache_key = f"user:{user_id}"
    
    # Check cache
    cached_data = cache.get(cache_key)
    if cached_data:
        print(f"✓ Cache hit: {cache_key}")
        return cached_data
    
    print(f"✗ Cache miss: {cache_key}")
    
    # Fetch from DB
    db = await get_database()
    user = await db.users.find_one({"user_id": user_id})
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Remove sensitive data
    user.pop("_id", None)
    user.pop("password", None)
    
    # Cache result
    cache.set(cache_key, user, TTL_STORE_INFO)
    print(f"✓ Cached: {cache_key} for {TTL_STORE_INFO}s")
    
    return user


# ============================================
# 5. CACHE INVALIDATION
# ============================================

# Add to any UPDATE/DELETE endpoints:

# When store is updated:
@router.put("/{store_id}")
async def update_store(store_id: str, update_data: dict):
    # ... update logic ...
    
    # Invalidate cache
    cache.invalidate_store(store_id)
    print(f"✓ Invalidated cache for store: {store_id}")
    
    return {"message": "Store updated"}

# When product is updated:
@router.put("/stores/{store_id}/products/{product_id}")
async def update_product(store_id: str, product_id: str, update_data: dict):
    # ... update logic ...
    
    # Invalidate cache
    cache.invalidate_inventory(store_id, product_id)
    print(f"✓ Invalidated cache for product: {product_id}")
    
    return {"message": "Product updated"}

# When order is placed:
@router.post("/")
async def create_order(order_data: dict):
    # ... create logic ...
    
    # Invalidate cache
    cache.invalidate_user_orders(order_data["user_id"])
    cache.invalidate_store_orders(order_data["store_id"])
    print(f"✓ Invalidated cache for new order")
    
    return {"message": "Order created"}

# When user profile is updated:
@router.put("/{user_id}")
async def update_user(user_id: str, update_data: dict):
    # ... update logic ...
    
    # Invalidate cache
    cache.delete(f"user:{user_id}")
    print(f"✓ Invalidated cache for user: {user_id}")
    
    return {"message": "User updated"}

