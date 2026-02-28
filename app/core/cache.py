"""
Redis Cache Manager
Handles caching for stores, inventory, and orders using Upstash Redis REST API
"""
import json
import httpx
from typing import Optional, Any, List
from datetime import timedelta
import os
from dotenv import load_dotenv

load_dotenv()

class CacheManager:
    """Upstash Redis cache manager for optimizing API responses"""
    
    def __init__(self):
        self.rest_url = os.getenv("UPSTASH_REDIS_REST_URL")
        self.rest_token = os.getenv("UPSTASH_REDIS_REST_TOKEN")
        
        if self.rest_url and self.rest_token:
            try:
                # Test connection with PING
                with httpx.Client(timeout=2.0) as client:
                    response = client.get(
                        f"{self.rest_url}/ping",
                        headers={"Authorization": f"Bearer {self.rest_token}"}
                    )
                    if response.status_code == 200:
                        self.enabled = True
                        print(f"✓ Upstash Redis connected: {self.rest_url}")
                    else:
                        self.enabled = False
                        print(f"⚠ Upstash Redis connection failed: {response.status_code}")
            except Exception as e:
                print(f"⚠ Upstash Redis not available: {e}. Caching disabled.")
                self.enabled = False
        else:
            print("⚠ Upstash Redis credentials not found. Caching disabled.")
            self.enabled = False
    
    def _make_request(self, command: str, *args) -> Optional[Any]:
        """Make REST API request to Upstash Redis"""
        if not self.enabled:
            return None
        
        try:
            # Build command array
            cmd = [command] + list(args)
            
            with httpx.Client(timeout=2.0) as client:
                response = client.post(
                    self.rest_url,
                    headers={
                        "Authorization": f"Bearer {self.rest_token}",
                        "Content-Type": "application/json"
                    },
                    json=cmd
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result.get("result")
                else:
                    print(f"Upstash request error: {response.status_code}")
                    return None
        except Exception as e:
            print(f"Upstash request exception: {e}")
            return None
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        if not self.enabled:
            return None
        
        try:
            value = self._make_request("GET", key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            print(f"Cache get error for {key}: {e}")
            return None
    
    def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        """Set value in cache with TTL (default 5 minutes)"""
        if not self.enabled:
            return False
        
        try:
            serialized = json.dumps(value, default=str)
            result = self._make_request("SETEX", key, str(ttl), serialized)
            return result == "OK"
        except Exception as e:
            print(f"Cache set error for {key}: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Delete key from cache"""
        if not self.enabled:
            return False
        
        try:
            result = self._make_request("DEL", key)
            return result is not None
        except Exception as e:
            print(f"Cache delete error for {key}: {e}")
            return False
    
    def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern"""
        if not self.enabled:
            return 0
        
        try:
            # Get all keys matching pattern
            keys = self._make_request("KEYS", pattern)
            if keys and len(keys) > 0:
                # Delete all matching keys
                result = self._make_request("DEL", *keys)
                return result if result else 0
            return 0
        except Exception as e:
            print(f"Cache delete pattern error for {pattern}: {e}")
            return 0
    
    def invalidate_store(self, store_id: str):
        """Invalidate all cache entries for a store"""
        patterns = [
            f"store:{store_id}",
            f"store:{store_id}:*",
            f"inventory:{store_id}:*",
            f"nearby_stores:*"  # Invalidate nearby stores when any store changes
        ]
        for pattern in patterns:
            if "*" in pattern:
                self.delete_pattern(pattern)
            else:
                self.delete(pattern)
    
    def invalidate_inventory(self, store_id: str, product_id: Optional[str] = None):
        """Invalidate inventory cache"""
        if product_id:
            self.delete(f"inventory:{store_id}:product:{product_id}")
        else:
            self.delete_pattern(f"inventory:{store_id}:*")
    
    def invalidate_user_orders(self, user_id: str):
        """Invalidate user orders cache"""
        self.delete_pattern(f"orders:user:{user_id}:*")
    
    def invalidate_store_orders(self, store_id: str):
        """Invalidate store orders cache"""
        self.delete_pattern(f"orders:store:{store_id}:*")

# Global cache instance
cache = CacheManager()

# Cache TTL constants (in seconds)
TTL_STORE_INFO = 600  # 10 minutes
TTL_NEARBY_STORES = 300  # 5 minutes
TTL_INVENTORY_LIST = 180  # 3 minutes
TTL_PRODUCT_INFO = 300  # 5 minutes
TTL_USER_ORDERS = 60  # 1 minute
TTL_STORE_ORDERS = 60  # 1 minute
