"""
OCR Service Router
Handles handwritten note image processing using Amazon Nova
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks, Query
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime

from app.db.mongodb import get_database
from app.services.ocr_service import OCRService

router = APIRouter(prefix="/ocr", tags=["OCR"])


# ==================== Request/Response Models ====================

class OCRJobResponse(BaseModel):
    """Response after uploading image for OCR processing"""
    job_id: str
    status: str
    message: str
    created_at: datetime


class ParsedItem(BaseModel):
    """Individual item parsed from handwritten note"""
    name: str
    quantity: float
    unit: Optional[str] = None
    confidence: float


class OCRResultResponse(BaseModel):
    """OCR processing result"""
    job_id: str
    status: str
    items: List[ParsedItem]
    raw_text: Optional[str] = None
    language_detected: Optional[str] = None
    notes: Optional[str] = None
    processing_time_ms: Optional[int] = None
    is_mock: bool = False


class OCRStatusResponse(BaseModel):
    """OCR job status"""
    job_id: str
    status: str  # PENDING, PROCESSING, COMPLETED, FAILED
    progress: int
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MatchedCartItem(BaseModel):
    """Product matched from OCR item"""
    product_id: str
    name: str
    brand: Optional[str] = None
    price: float
    mrp: float
    unit: str
    stock_quantity: int
    in_stock: bool
    match_confidence: float
    original_query: str
    matched_quantity: float
    line_total: float
    status: str = "perfect"
    modification_reason: Optional[str] = None


class MatchedCartResponse(BaseModel):
    """Response with matched cart from OCR"""
    job_id: str
    store_id: str
    ocr_items: List[dict]
    matched: List[MatchedCartItem]
    unmatched: List[dict]
    suggestions: List[dict]
    cart_total: float


# ==================== Dependencies ====================

async def get_ocr_service():
    """Get OCR service instance"""
    db = await get_database()
    return OCRService(db)


# ==================== API Endpoints ====================

@router.post("/upload", response_model=OCRJobResponse)
async def upload_handwritten_note(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    store_id: Optional[str] = Query(None, description="Store ID for product matching"),
    user_id: Optional[str] = Query(None, description="User ID for tracking"),
    service: OCRService = Depends(get_ocr_service)
):
    """
    Upload a handwritten shopping list image for OCR processing.

    **Supported formats:** JPEG, PNG, WebP (max 10MB)

    **Process:**
    1. Image is preprocessed (resize, contrast enhancement)
    2. Sent to Amazon Nova Multimodal for text extraction
    3. Items are parsed with quantities and units
    4. Results can be matched to store inventory

    **Returns:** job_id to track processing status

    **Example usage:**
    ```python
    import requests

    with open("shopping_list.jpg", "rb") as f:
        response = requests.post(
            "/api/v1/ocr/upload?store_id=STORE_123",
            files={"file": f}
        )
    job_id = response.json()["job_id"]
    ```
    """
    # Validate file type
    allowed_types = ["image/jpeg", "image/png", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{file.content_type}'. Allowed: {', '.join(allowed_types)}"
        )

    # Read and validate file size (max 10MB)
    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="File size exceeds 10MB limit"
        )

    if len(contents) < 1000:
        raise HTTPException(
            status_code=400,
            detail="File too small. Please upload a valid image."
        )

    # Create OCR job
    result = await service.create_job(
        image_data=contents,
        store_id=store_id,
        user_id=user_id,
        content_type=file.content_type
    )

    # Queue background processing
    background_tasks.add_task(process_ocr_job, service, result["job_id"])

    return OCRJobResponse(
        job_id=result["job_id"],
        status="PENDING",
        message="Image uploaded successfully. Processing started.",
        created_at=result["created_at"]
    )


@router.get("/status/{job_id}", response_model=OCRStatusResponse)
async def get_ocr_status(
    job_id: str,
    service: OCRService = Depends(get_ocr_service)
):
    """
    Check the processing status of an OCR job.

    **Status values:**
    - `PENDING` - Job created, waiting to process
    - `PROCESSING` - Currently extracting text
    - `COMPLETED` - Done, results available
    - `FAILED` - Error occurred

    Poll this endpoint until status is COMPLETED or FAILED.
    """
    result = await service.get_job_status(job_id)

    if not result:
        raise HTTPException(status_code=404, detail="Job not found")

    return OCRStatusResponse(**result)


@router.get("/result/{job_id}", response_model=OCRResultResponse)
async def get_ocr_result(
    job_id: str,
    service: OCRService = Depends(get_ocr_service)
):
    """
    Retrieve the parsed items from a completed OCR job.

    **Returns:**
    - `items` - List of extracted items with name, quantity, unit, and confidence
    - `raw_text` - The raw text extracted from the image
    - `language_detected` - Detected language (Hindi/English/Mixed)

    **Note:** Only available after job status is COMPLETED.
    """
    result = await service.get_job_result(job_id)

    if not result:
        raise HTTPException(status_code=404, detail="Job not found")

    if result["status"] == "PENDING" or result["status"] == "PROCESSING":
        raise HTTPException(
            status_code=202,
            detail=f"Processing not yet complete. Status: {result['status']}"
        )

    if result["status"] == "FAILED":
        raise HTTPException(
            status_code=500,
            detail=f"OCR processing failed. Please try again."
        )

    return OCRResultResponse(
        job_id=result["job_id"],
        status=result["status"],
        items=[ParsedItem(**item) for item in result.get("items", [])],
        raw_text=result.get("raw_text"),
        language_detected=result.get("language_detected"),
        notes=result.get("notes"),
        processing_time_ms=result.get("processing_time_ms"),
        is_mock=result.get("is_mock", False)
    )


@router.get("/cart/{job_id}", response_model=MatchedCartResponse)
async def get_matched_cart(
    job_id: str,
    store_id: str = Query(..., description="Store ID to match products against"),
    service: OCRService = Depends(get_ocr_service)
):
    """
    Get OCR results matched to store products.

    **Combines OCR extraction with inventory matching:**
    1. Takes extracted items from OCR
    2. Matches each item to store's product catalog
    3. Returns a ready-to-checkout cart

    **Returns:**
    - `matched` - Products found with prices and quantities
    - `unmatched` - Items that couldn't be matched
    - `suggestions` - Alternative products for unmatched items
    - `cart_total` - Total price of matched items

    **Example flow:**
    ```
    1. Upload image → /ocr/upload
    2. Wait for completion → /ocr/status/{job_id}
    3. Get cart → /ocr/cart/{job_id}?store_id=STORE_123
    4. Create order → /orders
    ```
    """
    result = await service.get_matched_cart(job_id, store_id)

    if "error" in result:
        if "not found" in result["error"].lower():
            raise HTTPException(status_code=404, detail=result["error"])
        elif "not ready" in result["error"].lower():
            raise HTTPException(status_code=202, detail=result["error"])
        else:
            raise HTTPException(status_code=500, detail=result["error"])

    return MatchedCartResponse(
        job_id=result["job_id"],
        store_id=result["store_id"],
        ocr_items=result.get("ocr_items", []),
        matched=[MatchedCartItem(**m) for m in result.get("matched", [])],
        unmatched=result.get("unmatched", []),
        suggestions=result.get("suggestions", []),
        cart_total=result.get("cart_total", 0)
    )


@router.post("/upload-and-match")
async def upload_and_match(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    store_id: str = Query(..., description="Store ID for product matching"),
    wait_for_result: bool = Query(False, description="Wait for OCR to complete (sync mode)"),
    is_demo: bool = Query(False, description="Whether user is in demo mode"),
    service: OCRService = Depends(get_ocr_service)
):
    """
    Upload image and immediately get matched cart (convenience endpoint).

    **Two modes:**
    - `wait_for_result=false` (default): Returns job_id immediately, poll for results
    - `wait_for_result=true`: Waits for OCR to complete and returns matched cart

    **Note:** Sync mode may take 3-10 seconds depending on image complexity.
    """
    # Validate file
    allowed_types = ["image/jpeg", "image/png", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(allowed_types)}"
        )

    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size exceeds 10MB limit")

    # Create job
    job_result = await service.create_job(
        image_data=contents,
        store_id=store_id,
        content_type=file.content_type
    )

    job_id = job_result["job_id"]

    if wait_for_result:
        # Sync mode - process immediately and wait
        await service.process_job(job_id)

        # Get matched cart
        cart_result = await service.get_matched_cart(job_id, store_id, is_demo=is_demo)

        if "error" in cart_result:
            raise HTTPException(status_code=500, detail=cart_result["error"])

        return {
            "mode": "sync",
            "job_id": job_id,
            "store_id": store_id,
            "ocr_items": cart_result.get("ocr_items", []),
            "matched": cart_result.get("matched", []),
            "unmatched": cart_result.get("unmatched", []),
            "suggestions": cart_result.get("suggestions", []),
            "cart_total": cart_result.get("cart_total", 0)
        }
    else:
        # Async mode - queue for background processing
        background_tasks.add_task(process_ocr_job, service, job_id)

        return {
            "mode": "async",
            "job_id": job_id,
            "status": "PENDING",
            "message": "Processing started. Poll /ocr/status/{job_id} for updates.",
            "cart_endpoint": f"/api/v1/ocr/cart/{job_id}?store_id={store_id}"
        }


# ==================== Background Task ====================

async def process_ocr_job(service: OCRService, job_id: str):
    """Background task to process OCR job."""
    try:
        await service.process_job(job_id)
    except Exception as e:
        import logging
        logging.error(f"Background OCR processing failed for {job_id}: {e}")
