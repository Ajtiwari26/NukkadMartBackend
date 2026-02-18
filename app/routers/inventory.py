"""
Inventory Service Router
Manages store inventory, product catalogs, and stock levels with MongoDB
"""
from fastapi import APIRouter, HTTPException, Depends, Query, Body
from typing import Optional, List
from datetime import datetime

from app.db.mongodb import get_database
from app.services.inventory_service import InventoryService
from app.models.product import (
    ProductCreate,
    ProductUpdate,
    ProductResponse,
    ProductListResponse,
    StockUpdate,
    StockUpdateResponse,
    BulkStockUpdate,
    InventorySummary,
    GSTInfo,
    ONDCProductInfo,
    ONDCCategory,
    ProductUnit
)
from app.models.inventory import (
    ProductMatchRequest,
    ProductMatchResponse
)
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter(prefix="/inventory", tags=["Inventory"])


# ==================== Simple Models for Quick Add ====================

class SimpleProduct(BaseModel):
    """Simplified product for quick addition"""
    name: str
    price: float
    mrp: Optional[float] = None
    category: str = "Grocery"
    unit: str = "piece"
    stock_quantity: int = 100
    brand: Optional[str] = None


class BulkProductCreate(BaseModel):
    """Bulk product creation request"""
    store_id: str
    products: List[SimpleProduct]


# ==================== Dependencies ====================

async def get_inventory_service():
    """Get inventory service instance"""
    db = await get_database()
    return InventoryService(db)


# ==================== Product CRUD Endpoints ====================

@router.post("/products", response_model=ProductResponse, status_code=201)
async def create_product(
    product: ProductCreate,
    service: InventoryService = Depends(get_inventory_service)
):
    """
    Create a new product in store inventory.

    Required fields:
    - name, category, price, mrp, store_id
    - gst_info with HSN code and GST rate

    ONDC compliance fields are optional but recommended.
    """
    try:
        created = await service.create_product(product)
        return ProductResponse(**created.model_dump())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: str,
    service: InventoryService = Depends(get_inventory_service)
):
    """Get product details by ID."""
    product = await service.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return ProductResponse(**product.model_dump())


@router.put("/products/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: str,
    update: ProductUpdate,
    service: InventoryService = Depends(get_inventory_service)
):
    """Update product details."""
    product = await service.update_product(product_id, update)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return ProductResponse(**product.model_dump())


@router.delete("/products/{product_id}")
async def delete_product(
    product_id: str,
    service: InventoryService = Depends(get_inventory_service)
):
    """Soft delete a product (deactivates it)."""
    success = await service.delete_product(product_id)
    if not success:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"message": "Product deactivated successfully", "product_id": product_id}


@router.post("/products/bulk")
async def bulk_create_products(request: BulkProductCreate):
    """
    Add multiple products at once.

    Simple format - just provide name, price, and optionally category/unit.
    Perfect for quickly adding your store's inventory.

    Example:
    ```json
    {
        "store_id": "STORE_123",
        "products": [
            {"name": "Rice 5kg", "price": 250, "category": "Grocery"},
            {"name": "Toor Dal 1kg", "price": 150, "category": "Grocery"},
            {"name": "Milk 1L", "price": 60, "category": "Dairy"},
            {"name": "Bread", "price": 40, "category": "Bakery"}
        ]
    }
    ```
    """
    import uuid
    from datetime import datetime

    db = await get_database()
    created_products = []
    now = datetime.utcnow()

    # Default GST rates by category
    gst_rates = {
        "Grocery": {"gst_rate": 5, "hsn_code": "0000"},
        "Dairy": {"gst_rate": 0, "hsn_code": "0401"},
        "Bakery": {"gst_rate": 0, "hsn_code": "1905"},
        "Beverages": {"gst_rate": 12, "hsn_code": "2201"},
        "Snacks": {"gst_rate": 12, "hsn_code": "1905"},
        "Personal Care": {"gst_rate": 18, "hsn_code": "3304"},
        "Home Care": {"gst_rate": 18, "hsn_code": "3402"},
    }

    for product in request.products:
        product_id = f"PROD_{uuid.uuid4().hex[:8].upper()}"

        # Get GST info based on category
        gst_info = gst_rates.get(product.category, {"gst_rate": 5, "hsn_code": "0000"})

        product_doc = {
            "product_id": product_id,
            "store_id": request.store_id,
            "name": product.name,
            "description": None,
            "category": product.category,
            "subcategory": "",
            "brand": product.brand or "",
            "price": product.price,
            "mrp": product.mrp or product.price,
            "cost_price": None,
            "unit": product.unit,
            "unit_value": 1,
            "barcode": None,
            "sku": None,
            "images": [],
            "thumbnail": None,
            "tags": [word.lower() for word in product.name.split()],
            "search_keywords": [],
            "stock_quantity": product.stock_quantity,
            "reorder_threshold": 10,
            "max_order_quantity": None,
            "gst_info": {
                "gst_rate": gst_info["gst_rate"],
                "hsn_code": gst_info["hsn_code"],
                "is_gst_inclusive": True,
                "cess_rate": 0
            },
            "ondc_info": None,
            "is_active": True,
            "is_available": True,
            "in_stock": product.stock_quantity > 0,
            "total_sold": 0,
            "view_count": 0,
            "created_at": now,
            "updated_at": now
        }

        await db.products.insert_one(product_doc)
        created_products.append({
            "product_id": product_id,
            "name": product.name,
            "price": product.price
        })

    # Update store product count
    await db.stores.update_one(
        {"store_id": request.store_id},
        {"$inc": {"total_products": len(created_products)}}
    )

    return {
        "success": True,
        "store_id": request.store_id,
        "created_count": len(created_products),
        "products": created_products
    }


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
    """
    List all products for a specific store.

    - Filter by category, subcategory
    - Filter to show only in-stock items
    - Full-text search
    - Paginated and sortable results
    """
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

    return ProductListResponse(
        products=[ProductResponse(**p.model_dump()) for p in result["products"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        total_pages=result["total_pages"]
    )


# ==================== Stock Management ====================

@router.put("/products/{product_id}/stock", response_model=StockUpdateResponse)
async def update_stock(
    product_id: str,
    stock_update: StockUpdate,
    service: InventoryService = Depends(get_inventory_service)
):
    """
    Update product stock quantity.

    Operations:
    - **set**: Set stock to exact quantity
    - **add**: Add to current stock (for restocking)
    - **subtract**: Subtract from current stock (for sales)
    - **reserve**: Reserve stock for pending order
    - **release**: Release reserved stock

    Include reason and reference_id for audit trail.
    """
    result = await service.update_stock(product_id, stock_update)
    if not result:
        raise HTTPException(status_code=404, detail="Product not found")
    return result


@router.post("/stores/{store_id}/stock/bulk", response_model=List[StockUpdateResponse])
async def bulk_update_stock(
    store_id: str,
    updates: BulkStockUpdate,
    service: InventoryService = Depends(get_inventory_service)
):
    """
    Bulk update stock for multiple products.

    Useful for inventory counts or bulk restocking.
    """
    results = await service.bulk_update_stock(store_id, updates.updates)
    return results


@router.get("/availability")
async def check_availability(
    store_id: str,
    product_ids: List[str] = Query(...),
    quantities: Optional[List[int]] = Query(None),
    service: InventoryService = Depends(get_inventory_service)
):
    """
    Check availability of multiple products.

    Returns stock status for each requested product,
    and whether all items are available in requested quantities.
    """
    items = []
    for i, product_id in enumerate(product_ids):
        qty = quantities[i] if quantities and i < len(quantities) else 1
        items.append({"product_id": product_id, "quantity": qty})

    result = await service.check_availability(store_id, items)
    return result


# ==================== Search & Matching ====================

@router.get("/search")
async def search_products(
    q: str = Query(..., min_length=1),
    store_id: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    service: InventoryService = Depends(get_inventory_service)
):
    """
    Search products by name, tags, or category.

    Uses MongoDB text search for fuzzy matching.
    """
    products = await service.search_products(q, store_id, category, limit)
    return {
        "query": q,
        "results": [ProductResponse(**p.model_dump()) for p in products],
        "total": len(products)
    }


@router.post("/match-products", response_model=ProductMatchResponse)
async def match_products_from_ocr(
    request: ProductMatchRequest,
    service: InventoryService = Depends(get_inventory_service)
):
    """
    Match OCR-parsed items to actual store products.

    Used to convert handwritten list items to purchasable products.

    Input format:
    ```json
    {
        "store_id": "STORE_123",
        "items": [
            {"name": "rice", "quantity": 2, "unit": "kg"},
            {"name": "dal", "quantity": 1, "unit": "kg"},
            {"name": "milk", "quantity": 2, "unit": "L"}
        ]
    }
    ```

    Returns:
    - **matched**: Products found with confidence scores
    - **unmatched**: Items that couldn't be matched
    - **suggestions**: Alternative products for unmatched items
    - **cart_total**: Total price of matched items
    """
    result = await service.match_products_from_ocr(request.store_id, request.items)
    return result


@router.get("/barcode/{barcode}")
async def get_product_by_barcode(
    barcode: str,
    store_id: str,
    service: InventoryService = Depends(get_inventory_service)
):
    """
    Get product by barcode (EAN/UPC).

    Useful for quick inventory lookup via barcode scanner.
    """
    product = await service.get_product_by_barcode(barcode, store_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return ProductResponse(**product.model_dump())


# ==================== Inventory Analytics ====================

@router.get("/stores/{store_id}/summary", response_model=InventorySummary)
async def get_inventory_summary(
    store_id: str,
    service: InventoryService = Depends(get_inventory_service)
):
    """
    Get inventory summary with alerts.

    Returns:
    - Total product counts
    - Out of stock and low stock counts
    - Total inventory value
    - Alerts for products needing attention
    """
    summary = await service.get_inventory_summary(store_id)
    return summary


@router.get("/stores/{store_id}/low-stock")
async def get_low_stock_products(
    store_id: str,
    service: InventoryService = Depends(get_inventory_service)
):
    """Get products that are low on stock (below reorder threshold)."""
    products = await service.get_low_stock_products(store_id)
    return {
        "store_id": store_id,
        "count": len(products),
        "products": [ProductResponse(**p.model_dump()) for p in products]
    }


@router.get("/stores/{store_id}/out-of-stock")
async def get_out_of_stock_products(
    store_id: str,
    service: InventoryService = Depends(get_inventory_service)
):
    """Get products that are out of stock."""
    products = await service.get_out_of_stock_products(store_id)
    return {
        "store_id": store_id,
        "count": len(products),
        "products": [ProductResponse(**p.model_dump()) for p in products]
    }


# ==================== Categories ====================

@router.get("/categories")
async def get_categories():
    """Get list of available product categories (ONDC compliant)."""
    return {
        "categories": [
            {"code": cat.value, "name": cat.value}
            for cat in ONDCCategory
        ]
    }


@router.get("/units")
async def get_units():
    """Get list of available product units."""
    return {
        "units": [
            {"code": unit.value, "name": unit.name.replace("_", " ").title()}
            for unit in ProductUnit
        ]
    }


@router.get("/gst-rates")
async def get_gst_rates():
    """Get list of standard GST rates in India."""
    return {
        "rates": [
            {"rate": 0, "description": "Exempt (Essential items)"},
            {"rate": 5, "description": "5% GST (Basic necessities)"},
            {"rate": 12, "description": "12% GST (Processed foods)"},
            {"rate": 18, "description": "18% GST (Standard rate)"},
            {"rate": 28, "description": "28% GST (Luxury items)"}
        ]
    }


# ==================== Quick Add Templates ====================

@router.get("/templates/quick-add")
async def get_quick_add_templates():
    """
    Get product templates for quick addition.

    Common kirana store items with pre-filled GST and category info.
    """
    return {
        "templates": [
            {
                "name": "Rice",
                "category": "Groceries",
                "subcategory": "Rice & Grains",
                "unit": "kg",
                "gst_info": {"gst_rate": 5, "hsn_code": "10063020", "is_gst_inclusive": True},
                "ondc_category": "Grocery",
                "tags": ["rice", "staple", "grains"]
            },
            {
                "name": "Toor Dal",
                "category": "Groceries",
                "subcategory": "Pulses & Lentils",
                "unit": "kg",
                "gst_info": {"gst_rate": 5, "hsn_code": "07134000", "is_gst_inclusive": True},
                "ondc_category": "Grocery",
                "tags": ["dal", "pulses", "protein"]
            },
            {
                "name": "Sugar",
                "category": "Groceries",
                "subcategory": "Sugar & Sweeteners",
                "unit": "kg",
                "gst_info": {"gst_rate": 5, "hsn_code": "17019910", "is_gst_inclusive": True},
                "ondc_category": "Grocery",
                "tags": ["sugar", "sweetener", "essential"]
            },
            {
                "name": "Salt",
                "category": "Groceries",
                "subcategory": "Spices & Condiments",
                "unit": "kg",
                "gst_info": {"gst_rate": 5, "hsn_code": "25010010", "is_gst_inclusive": True},
                "ondc_category": "Grocery",
                "tags": ["salt", "essential", "cooking"]
            },
            {
                "name": "Cooking Oil",
                "category": "Groceries",
                "subcategory": "Edible Oils",
                "unit": "L",
                "gst_info": {"gst_rate": 5, "hsn_code": "15079010", "is_gst_inclusive": True},
                "ondc_category": "Grocery",
                "tags": ["oil", "cooking", "essential"]
            },
            {
                "name": "Milk",
                "category": "Dairy",
                "subcategory": "Milk",
                "unit": "L",
                "gst_info": {"gst_rate": 0, "hsn_code": "04011000", "is_gst_inclusive": True},
                "ondc_category": "Dairy",
                "tags": ["milk", "dairy", "fresh"]
            },
            {
                "name": "Bread",
                "category": "Bakery",
                "subcategory": "Bread",
                "unit": "packet",
                "gst_info": {"gst_rate": 0, "hsn_code": "19051000", "is_gst_inclusive": True},
                "ondc_category": "Bakery",
                "tags": ["bread", "bakery", "breakfast"]
            },
            {
                "name": "Butter",
                "category": "Dairy",
                "subcategory": "Butter & Cheese",
                "unit": "g",
                "unit_value": 100,
                "gst_info": {"gst_rate": 12, "hsn_code": "04051000", "is_gst_inclusive": True},
                "ondc_category": "Dairy",
                "tags": ["butter", "dairy", "spread"]
            },
            {
                "name": "Atta (Wheat Flour)",
                "category": "Groceries",
                "subcategory": "Flour",
                "unit": "kg",
                "gst_info": {"gst_rate": 0, "hsn_code": "11010000", "is_gst_inclusive": True},
                "ondc_category": "Grocery",
                "tags": ["atta", "flour", "wheat", "staple"]
            },
            {
                "name": "Tea",
                "category": "Beverages",
                "subcategory": "Tea & Coffee",
                "unit": "g",
                "unit_value": 250,
                "gst_info": {"gst_rate": 5, "hsn_code": "09021000", "is_gst_inclusive": True},
                "ondc_category": "Grocery",
                "tags": ["tea", "chai", "beverage"]
            }
        ]
    }
