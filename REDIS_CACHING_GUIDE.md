# Redis Caching Implementation Guide

## Setup Redis

### Install Redis

```bash
# macOS
brew install redis
brew services start redis

# Ubuntu/Debian
sudo apt-get update
sudo apt-get install redis-server
sudo systemctl start redis
sudo systemctl enable redis

# Docker
docker run -d --name redis -p 6379:6379 redis:alpine

# Verify installation
redis-cli ping
# Should return: PONG
```

### Install Python Redis Client

```bash
cd backend
pip install redis
# or
pip install -r requirements.txt  # if redis is added to requirements.txt
```

### Update .env

```env
REDIS_URL=redis://localhost:6379/0
```

## Implementation Pattern

### 1. Import Cache Manager

```python
from app.core.cache import cache, TTL_STORE_INFO, TTL_NEARBY_STORES, TTL_INVENTORY_LIST
```

### 2. Cache Pattern for GET Endpoints

```python
@router.get("/stores/{store_id}")
async def get_store(store_id: str):
    # 1. Check cache first
    cache_key = f"store:{store_id}"
    cached_data = cache.get(cache_key)
    if cached_data:
        print(f"Cache hit: {cache_key}")
        return cached_data
    
    # 2. Fetch from database
    db = await get_database()
    store = await db.stores.find_one({"store_id": store_id})
    
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    # 3. Cache the result
    cache.set(cache_key, store, TTL_STORE_INFO)
    print(f"Cache miss: {cache_key} - cached for {TTL_STORE_INFO}s")
    
    return store
```

### 3. Cache Invalidation for POST/PUT/DELETE

```python
@router.put("/stores/{store_id}")
async def update_store(store_id: str, update_data: dict):
    # 1. Update database
    db = await get_database()
    result = await db.stores.update_one(
        {"store_id": store_id},
        {"$set": update_data}
    )
    
    # 2. Invalidate cache
    cache.invalidate_store(store_id)
    
    return {"message": "Store updated"}
```

## Endpoints to Cache

### High Priority (Implement First)

#### 1. Nearby Stores
**Endpoint**: `GET /api/v1/stores/nearby`
**Cache Key**: `nearby_stores:{lat}:{lng}:{radius}`
**TTL**: 5 minutes
**Invalidate**: When any store is created/updated/deleted

```python
@router.get("/nearby")
async def get_nearby_stores(
    lat: float,
    lng: float,
    radius_km: float = 10.0
):
    # Round coordinates to 2 decimals for cache key
    lat_rounded = round(lat, 2)
    lng_rounded = round(lng, 2)
    cache_key = f"nearby_stores:{lat_rounded}:{lng_rounded}:{radius_km}"
    
    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data
    
    # Fetch from DB
    stores = await fetch_nearby_stores(lat, lng, radius_km)
    
    # Cache result
    cache.set(cache_key, stores, TTL_NEARBY_STORES)
    return stores
```

#### 2. Store Details
**Endpoint**: `GET /api/v1/stores/{store_id}`
**Cache Key**: `store:{store_id}`
**TTL**: 10 minutes
**Invalidate**: When store is updated

#### 3. Store Products/Inventory
**Endpoint**: `GET /api/v1/inventory/stores/{store_id}/products`
**Cache Key**: `inventory:{store_id}:products`
**TTL**: 3 minutes
**Invalidate**: When inventory is updated

```python
@router.get("/stores/{store_id}/products")
async def list_store_products(store_id: str, limit: int = 200):
    cache_key = f"inventory:{store_id}:products:{limit}"
    
    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data
    
    # Fetch from DB
    products = await fetch_store_products(store_id, limit)
    
    # Cache result
    cache.set(cache_key, products, TTL_INVENTORY_LIST)
    return products
```

#### 4. Single Product
**Endpoint**: `GET /api/v1/inventory/stores/{store_id}/products/{product_id}`
**Cache Key**: `inventory:{store_id}:product:{product_id}`
**TTL**: 5 minutes
**Invalidate**: When product is updated

### Medium Priority

#### 5. User Orders
**Endpoint**: `GET /api/v1/orders/user/{user_id}`
**Cache Key**: `orders:user:{user_id}:recent`
**TTL**: 1 minute
**Invalidate**: When new order is placed

#### 6. Store Orders
**Endpoint**: `GET /api/v1/orders/store/{store_id}`
**Cache Key**: `orders:store:{store_id}:active`
**TTL**: 1 minute
**Invalidate**: When order status changes

### Low Priority (Optional)

#### 7. Store Dashboard Stats
**Cache Key**: `dashboard:{store_id}:stats`
**TTL**: 5 minutes

#### 8. Search Results (Short TTL)
**Cache Key**: `search:{store_id}:{query_hash}`
**TTL**: 2 minutes

## Cache Invalidation Patterns

### Store Updated
```python
cache.invalidate_store(store_id)
# Invalidates:
# - store:{store_id}
# - store:{store_id}:*
# - inventory:{store_id}:*
# - nearby_stores:*
```

### Product Updated
```python
cache.invalidate_inventory(store_id, product_id)
# Invalidates:
# - inventory:{store_id}:product:{product_id}
# - inventory:{store_id}:products:*
```

### Order Placed
```python
cache.invalidate_user_orders(user_id)
cache.invalidate_store_orders(store_id)
# Invalidates:
# - orders:user:{user_id}:*
# - orders:store:{store_id}:*
```

## Example: Complete Implementation

### stores.py

```python
from app.core.cache import cache, TTL_STORE_INFO, TTL_NEARBY_STORES

@router.get("/nearby")
async def get_nearby_stores(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(10.0, ge=0, le=50)
):
    # Round for cache key
    lat_r = round(lat, 2)
    lng_r = round(lng, 2)
    cache_key = f"nearby_stores:{lat_r}:{lng_r}:{radius_km}"
    
    # Check cache
    cached = cache.get(cache_key)
    if cached:
        print(f"✓ Cache hit: {cache_key}")
        return cached
    
    print(f"✗ Cache miss: {cache_key}")
    
    # Fetch from DB
    db = await get_database()
    stores = []
    async for store in db.stores.find({"status": "ACTIVE"}):
        distance = haversine_distance(lat, lng, 
                                     store["address"]["coordinates"]["lat"],
                                     store["address"]["coordinates"]["lng"])
        if distance <= radius_km:
            stores.append({
                "store_id": store["store_id"],
                "name": store["name"],
                "distance_km": round(distance, 2),
                # ... other fields
            })
    
    # Sort by distance
    stores.sort(key=lambda x: x["distance_km"])
    
    # Cache result
    cache.set(cache_key, stores, TTL_NEARBY_STORES)
    print(f"✓ Cached: {cache_key} for {TTL_NEARBY_STORES}s")
    
    return stores

@router.put("/{store_id}")
async def update_store(store_id: str, update_data: dict):
    db = await get_database()
    
    # Update DB
    result = await db.stores.update_one(
        {"store_id": store_id},
        {"$set": update_data}
    )
    
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Store not found")
    
    # Invalidate cache
    cache.invalidate_store(store_id)
    print(f"✓ Invalidated cache for store: {store_id}")
    
    return {"message": "Store updated successfully"}
```

## Testing Cache

### 1. Test Cache Hit/Miss

```bash
# First request (cache miss)
curl http://localhost:8000/api/v1/stores/nearby?lat=23.12&lng=77.49

# Second request (cache hit)
curl http://localhost:8000/api/v1/stores/nearby?lat=23.12&lng=77.49
```

Check logs for:
```
✗ Cache miss: nearby_stores:23.12:77.49:10.0
✓ Cached: nearby_stores:23.12:77.49:10.0 for 300s
✓ Cache hit: nearby_stores:23.12:77.49:10.0
```

### 2. Test Cache Invalidation

```bash
# Update store
curl -X PUT http://localhost:8000/api/v1/stores/STORE_123 \
  -H "Content-Type: application/json" \
  -d '{"name": "Updated Store"}'

# Check logs for:
# ✓ Invalidated cache for store: STORE_123
```

### 3. Monitor Redis

```bash
# Connect to Redis CLI
redis-cli

# List all keys
KEYS *

# Get specific key
GET "store:STORE_123"

# Check TTL
TTL "store:STORE_123"

# Monitor all commands
MONITOR
```

## Performance Monitoring

### Add Timing Logs

```python
import time

@router.get("/stores/{store_id}")
async def get_store(store_id: str):
    start_time = time.time()
    
    cache_key = f"store:{store_id}"
    cached_data = cache.get(cache_key)
    
    if cached_data:
        elapsed = (time.time() - start_time) * 1000
        print(f"✓ Cache hit: {cache_key} ({elapsed:.2f}ms)")
        return cached_data
    
    # DB fetch
    db = await get_database()
    store = await db.stores.find_one({"store_id": store_id})
    
    elapsed = (time.time() - start_time) * 1000
    print(f"✗ Cache miss: {cache_key} ({elapsed:.2f}ms)")
    
    cache.set(cache_key, store, TTL_STORE_INFO)
    return store
```

Expected results:
- Cache hit: 1-5ms
- Cache miss (DB): 50-200ms
- **40-200x faster with cache!**

## Troubleshooting

### Redis Not Available
Cache manager handles this gracefully:
```
⚠ Redis not available: Connection refused. Caching disabled.
```
App continues to work without caching.

### Cache Not Updating
1. Check if invalidation is called after updates
2. Verify cache key matches between get/set/delete
3. Check Redis connection: `redis-cli ping`

### Memory Issues
```bash
# Check Redis memory usage
redis-cli INFO memory

# Set max memory (e.g., 256MB)
redis-cli CONFIG SET maxmemory 256mb
redis-cli CONFIG SET maxmemory-policy allkeys-lru
```

## Next Steps

1. ✅ Create `backend/app/core/cache.py`
2. ✅ Add Redis to `.env`
3. ⬜ Update `stores.py` router with caching
4. ⬜ Update `inventory.py` router with caching
5. ⬜ Update `orders.py` router with caching
6. ⬜ Test cache hit/miss rates
7. ⬜ Monitor performance improvements
