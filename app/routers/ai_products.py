"""
AI-Powered Product Parsing Router
Intelligently extracts product information from text, images, or files
"""
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import List, Optional
import re
import json

from app.services.ai_service import get_ai_service
from app.db.mongodb import get_database

router = APIRouter(prefix="/ai-products", tags=["AI Products"])


class ParsedProduct(BaseModel):
    """Parsed product information"""
    name: str
    category: str
    price: float
    quantity: Optional[str] = None
    unit: Optional[str] = "piece"
    brand: Optional[str] = None
    mrp: Optional[float] = None
    stock_quantity: int = 50


class ProductParseRequest(BaseModel):
    """Request to parse product list"""
    text: str
    store_id: str


class ProductParseResponse(BaseModel):
    """Response with parsed products"""
    success: bool
    products: List[ParsedProduct]
    raw_text: str
    parsed_count: int


@router.post("/parse-text", response_model=ProductParseResponse)
async def parse_product_text(request: ProductParseRequest):
    """
    Parse product list from text using AI.
    
    Supports various formats:
    - "Full Cream Milk (500ml) - ₹33"
    - "Toned Milk 500ml Rs 27"
    - "Curd Pouch 400g: 35"
    - "Amul Butter 100g - 58 rupees"
    
    AI extracts:
    - Product name
    - Category (auto-detected)
    - Price
    - Quantity/Size
    - Unit (ml, g, kg, L, piece)
    - Brand (if mentioned)
    """
    ai_service = get_ai_service()
    
    if not ai_service.is_available():
        # Fallback to rule-based parsing
        products = _rule_based_parse(request.text)
    else:
        # Use AI for intelligent parsing
        products = await _ai_parse_products(request.text, ai_service)
    
    return ProductParseResponse(
        success=True,
        products=products,
        raw_text=request.text,
        parsed_count=len(products)
    )


@router.post("/parse-image")
async def parse_product_image(
    store_id: str = Form(...),
    file: UploadFile = File(...)
):
    """
    Parse product list from uploaded image using OCR + AI.
    
    Supports:
    - Photos of handwritten lists
    - Screenshots of product lists
    - Price tags
    - Invoices
    - Any image size/dimension (will be optimized automatically)
    """
    from PIL import Image
    import io
    
    ai_service = get_ai_service()
    
    if not ai_service.is_available():
        raise HTTPException(
            status_code=503,
            detail="AI service not available. Please check GROQ_API_KEY in .env file."
        )
    
    try:
        # Read image
        image_data = await file.read()
        
        # Open image with PIL to process it
        image = Image.open(io.BytesIO(image_data))
        
        # Convert to RGB if needed (handles RGBA, grayscale, etc.)
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Resize if image is too large (Groq has limits)
        max_dimension = 2048
        width, height = image.size
        
        if width > max_dimension or height > max_dimension:
            # Calculate new dimensions maintaining aspect ratio
            if width > height:
                new_width = max_dimension
                new_height = int(height * (max_dimension / width))
            else:
                new_height = max_dimension
                new_width = int(width * (max_dimension / height))
            
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            print(f"Resized image from {width}x{height} to {new_width}x{new_height}")
        
        # Optimize image quality vs size
        output = io.BytesIO()
        image.save(output, format='JPEG', quality=85, optimize=True)
        optimized_image_data = output.getvalue()
        
        # Check final size
        image_size_mb = len(optimized_image_data) / (1024 * 1024)
        print(f"Image size: {image_size_mb:.2f}MB")
        
        if image_size_mb > 4:
            # Further reduce quality if still too large
            output = io.BytesIO()
            image.save(output, format='JPEG', quality=70, optimize=True)
            optimized_image_data = output.getvalue()
            image_size_mb = len(optimized_image_data) / (1024 * 1024)
            print(f"Reduced image size to: {image_size_mb:.2f}MB")
        
        # Use AI OCR to extract text
        ocr_result = await ai_service.extract_shopping_list(
            image_data=optimized_image_data,
            image_format='jpeg'
        )
        
        if not ocr_result.get("success"):
            error_msg = ocr_result.get("error", "Unknown error")
            raise HTTPException(
                status_code=400,
                detail=f"OCR failed: {error_msg}"
            )
        
        # Extract raw text from OCR result
        raw_text = ocr_result.get("raw_text", "").strip()
        
        if not raw_text:
            raise HTTPException(
                status_code=400,
                detail="No text could be extracted from image. Please ensure the image contains readable text."
            )
        
        print(f"Extracted text: {raw_text[:200]}...")
        
        # Parse extracted text using AI
        products = await _ai_parse_products(raw_text, ai_service)
        
        if len(products) == 0:
            # Try rule-based parsing as fallback
            products = _rule_based_parse(raw_text)
        
        return {
            "success": True,
            "products": products,
            "raw_text": raw_text,
            "parsed_count": len(products),
            "ocr_confidence": ocr_result.get("confidence", 0.85),
            "image_size_mb": round(image_size_mb, 2)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Image parsing error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process image: {str(e)}"
        )


def _detect_category(name: str) -> str:
    """Detect category from product name"""
    category_map = {
        'Dairy': ['milk', 'curd', 'butter', 'paneer', 'cheese', 'ghee', 'cream', 'yogurt', 'dahi'],
        'Bakery': ['bread', 'cake', 'biscuit', 'cookie', 'rusk', 'bun', 'pav'],
        'Beverages': ['tea', 'coffee', 'juice', 'cola', 'pepsi', 'coke', 'drink', 'water'],
        'Snacks': ['chips', 'namkeen', 'chocolate', 'candy', 'wafer', 'kurkure'],
        'Personal Care': ['soap', 'shampoo', 'toothpaste', 'cream', 'lotion', 'oil'],
        'Home Care': ['detergent', 'cleaner', 'soap', 'liquid', 'powder'],
        'Fruits & Vegetables': ['apple', 'banana', 'potato', 'onion', 'tomato', 'fruit', 'vegetable'],
    }
    
    name_lower = name.lower()
    for cat, keywords in category_map.items():
        if any(kw in name_lower for kw in keywords):
            return cat
    return 'Grocery'


async def _ai_parse_products(text: str, ai_service) -> List[ParsedProduct]:
    """Use AI to intelligently parse product list"""
    
    prompt = f"""Parse this product list and extract structured information for each product.

Product List:
{text}

For each product, extract:
1. name: Full product name (include size/quantity in name if part of product identity)
2. category: One of [Dairy, Grocery, Bakery, Beverages, Snacks, Personal Care, Home Care, Fruits & Vegetables, Frozen Foods]
3. price: Price in rupees (numeric only)
4. quantity: Size/quantity mentioned (e.g., "500ml", "1kg", "200g")
5. unit: Unit type (ml, L, g, kg, piece, pack)
6. brand: Brand name if mentioned (null if not mentioned)
7. mrp: MRP if different from price (null if same)

Return ONLY a valid JSON array of products. Example:
[
  {{"name": "Full Cream Milk", "category": "Dairy", "price": 33, "quantity": "500ml", "unit": "ml", "brand": null, "mrp": null}},
  {{"name": "Amul Butter", "category": "Dairy", "price": 58, "quantity": "100g", "unit": "g", "brand": "Amul", "mrp": null}}
]

JSON array:"""

    try:
        # Call Groq API
        from groq import AsyncGroq
        from app.config import settings
        
        client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        
        response = await client.chat.completions.create(
            model=settings.GROQ_TEXT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a product data extraction expert. Extract product information and return ONLY valid JSON array. No explanations."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.1,
            max_tokens=2000
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Extract JSON from response
        json_match = re.search(r'\[.*\]', result_text, re.DOTALL)
        if json_match:
            result_text = json_match.group(0)
        
        parsed_data = json.loads(result_text)
        
        products = []
        for item in parsed_data:
            products.append(ParsedProduct(
                name=item.get("name", "Unknown Product"),
                category=item.get("category", "Grocery"),
                price=float(item.get("price", 0)),
                quantity=item.get("quantity"),
                unit=item.get("unit", "piece"),
                brand=item.get("brand"),
                mrp=float(item.get("mrp")) if item.get("mrp") else None,
                stock_quantity=50
            ))
        
        return products
        
    except Exception as e:
        print(f"AI parsing failed: {e}, falling back to rule-based")
        return _rule_based_parse(text)


def _rule_based_parse(text: str) -> List[ParsedProduct]:
    """Fallback rule-based parsing"""
    products = []
    lines = text.split('\n')
    
    # Category keywords
    category_map = {
        'Dairy': ['milk', 'curd', 'butter', 'paneer', 'cheese', 'ghee', 'cream', 'yogurt', 'dahi'],
        'Bakery': ['bread', 'cake', 'biscuit', 'cookie', 'rusk', 'bun', 'pav'],
        'Beverages': ['tea', 'coffee', 'juice', 'cola', 'pepsi', 'coke', 'drink', 'water'],
        'Snacks': ['chips', 'namkeen', 'chocolate', 'candy', 'wafer', 'kurkure'],
        'Personal Care': ['soap', 'shampoo', 'toothpaste', 'cream', 'lotion', 'oil'],
        'Home Care': ['detergent', 'cleaner', 'soap', 'liquid', 'powder'],
        'Fruits & Vegetables': ['apple', 'banana', 'potato', 'onion', 'tomato', 'fruit', 'vegetable'],
    }
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Try multiple patterns
        patterns = [
            # "Product Name (quantity) - ₹price" or "Product Name (quantity) - Rs price"
            r'^(.+?)\s*\(([^)]+)\)\s*[-:]\s*[₹Rs.\s]*(\d+(?:\.\d+)?)',
            # "Product Name quantity - price"
            r'^(.+?)\s+(\d+(?:\.\d+)?(?:ml|l|g|kg|gm|gram|litre|liter))\s*[-:]\s*[₹Rs.\s]*(\d+(?:\.\d+)?)',
            # "Product Name - price"
            r'^(.+?)\s*[-:]\s*[₹Rs.\s]*(\d+(?:\.\d+)?)\s*$',
        ]
        
        matched = False
        for pattern in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                if len(match.groups()) == 3:
                    name, quantity_or_price, price = match.groups()
                    # Check if second group is quantity or price
                    if re.search(r'(ml|l|g|kg|gm|gram|litre|liter)', quantity_or_price, re.IGNORECASE):
                        quantity = quantity_or_price
                    else:
                        # Second group is price, no quantity
                        price = quantity_or_price
                        quantity = None
                else:
                    name = match.group(1)
                    price = match.group(2)
                    quantity = None
                
                name = name.strip()
                price = float(price)
                
                # Detect category
                category = 'Grocery'
                name_lower = name.lower()
                for cat, keywords in category_map.items():
                    if any(kw in name_lower for kw in keywords):
                        category = cat
                        break
                
                # Extract unit
                unit = 'piece'
                if quantity:
                    if 'ml' in quantity.lower():
                        unit = 'ml'
                    elif 'l' in quantity.lower():
                        unit = 'L'
                    elif 'kg' in quantity.lower():
                        unit = 'kg'
                    elif 'g' in quantity.lower():
                        unit = 'g'
                
                # Try to extract brand (common brands)
                brand = None
                brands = ['amul', 'mother dairy', 'nestle', 'britannia', 'parle', 'haldiram', 'bikaji']
                for b in brands:
                    if b in name_lower:
                        brand = b.title()
                        break
                
                products.append(ParsedProduct(
                    name=name,
                    category=category,
                    price=price,
                    quantity=quantity,
                    unit=unit,
                    brand=brand,
                    stock_quantity=50
                ))
                
                matched = True
                break
        
        if not matched:
            print(f"Could not parse line: {line}")
    
    return products


@router.post("/create-from-parsed")
async def create_products_from_parsed(
    store_id: str,
    products: List[ParsedProduct]
):
    """
    Create products in database from parsed product list.
    Allows review and editing before final creation.
    """
    import uuid
    from datetime import datetime
    
    db = await get_database()
    created_products = []
    now = datetime.utcnow()
    
    # GST rates by category
    gst_rates = {
        "Grocery": {"gst_rate": 5, "hsn_code": "0000"},
        "Dairy": {"gst_rate": 0, "hsn_code": "0401"},
        "Bakery": {"gst_rate": 0, "hsn_code": "1905"},
        "Beverages": {"gst_rate": 12, "hsn_code": "2201"},
        "Snacks": {"gst_rate": 12, "hsn_code": "1905"},
        "Personal Care": {"gst_rate": 18, "hsn_code": "3304"},
        "Home Care": {"gst_rate": 18, "hsn_code": "3402"},
        "Fruits & Vegetables": {"gst_rate": 0, "hsn_code": "0701"},
        "Frozen Foods": {"gst_rate": 12, "hsn_code": "1602"},
    }
    
    for product in products:
        product_id = f"PROD_{uuid.uuid4().hex[:8].upper()}"
        
        gst_info = gst_rates.get(product.category, {"gst_rate": 5, "hsn_code": "0000"})
        
        product_doc = {
            "product_id": product_id,
            "store_id": store_id,
            "name": product.name,
            "description": f"{product.quantity or ''} {product.brand or ''}".strip() or None,
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
            "price": product.price,
            "category": product.category
        })
    
    # Update store product count
    await db.stores.update_one(
        {"store_id": store_id},
        {"$inc": {"total_products": len(created_products)}}
    )
    
    return {
        "success": True,
        "store_id": store_id,
        "created_count": len(created_products),
        "products": created_products
    }
