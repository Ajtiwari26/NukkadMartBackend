"""
OCR Service
Handles handwritten note processing and item extraction
"""
import uuid
import asyncio
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from io import BytesIO

from PIL import Image
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.services.ai_service import AIService, get_ai_service
from app.services.inventory_service import InventoryService
from app.db.redis import RedisClient
from app.config import settings

logger = logging.getLogger(__name__)


class OCRService:
    """Service for OCR processing of handwritten shopping lists"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.ocr_jobs = db.ocr_jobs
        self.ai = get_ai_service()

    async def create_job(
        self,
        image_data: bytes,
        store_id: Optional[str] = None,
        user_id: Optional[str] = None,
        content_type: str = "image/jpeg"
    ) -> Dict[str, Any]:
        """
        Create a new OCR processing job.

        Args:
            image_data: Raw image bytes
            store_id: Optional store ID for product matching
            user_id: Optional user ID for tracking
            content_type: Image MIME type

        Returns:
            Job information with job_id
        """
        job_id = f"ocr_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow()

        # Preprocess image
        processed_image, image_format = await self._preprocess_image(image_data, content_type)

        # Store job in database
        job_doc = {
            "job_id": job_id,
            "store_id": store_id,
            "user_id": user_id,
            "status": "PENDING",
            "image_format": image_format,
            "image_size": len(processed_image),
            "items": [],
            "raw_text": None,
            "error": None,
            "processing_time_ms": None,
            "created_at": now,
            "updated_at": now
        }

        # Store image data directly in MongoDB (Redis REST API has URL length limits)
        job_doc["_image_data"] = processed_image
        
        await self.ocr_jobs.insert_one(job_doc)

        logger.info(f"Created OCR job {job_id}")

        return {
            "job_id": job_id,
            "status": "PENDING",
            "message": "Image uploaded successfully. Processing started.",
            "created_at": now
        }

    async def process_job(self, job_id: str) -> Dict[str, Any]:
        """
        Process an OCR job - extract items from the image.

        Args:
            job_id: The job ID to process

        Returns:
            Processing result
        """
        start_time = datetime.utcnow()

        # Get job from database
        job = await self.ocr_jobs.find_one({"job_id": job_id})
        if not job:
            return {"error": "Job not found"}

        try:
            # Update status to processing
            await self.ocr_jobs.update_one(
                {"job_id": job_id},
                {"$set": {"status": "PROCESSING", "updated_at": datetime.utcnow()}}
            )

            # Get image data from database
            image_data = job.get("_image_data")

            if not image_data:
                raise ValueError("Image data not found")

            # Call AI service for OCR
            image_format = job.get("image_format", "jpeg")
            ocr_result = await self.ai.extract_shopping_list(image_data, image_format)

            # Process results
            items = ocr_result.get("items", [])
            raw_text = ocr_result.get("raw_text", "")

            # Calculate processing time
            end_time = datetime.utcnow()
            processing_time_ms = int((end_time - start_time).total_seconds() * 1000)

            # Update job with results
            await self.ocr_jobs.update_one(
                {"job_id": job_id},
                {
                    "$set": {
                        "status": "COMPLETED",
                        "items": items,
                        "raw_text": raw_text,
                        "language_detected": ocr_result.get("language_detected"),
                        "notes": ocr_result.get("notes"),
                        "processing_time_ms": processing_time_ms,
                        "updated_at": end_time,
                        "is_mock": ocr_result.get("is_mock", False)
                    },
                    "$unset": {"_image_data": ""}  # Remove image data after processing
                }
            )

            logger.info(f"OCR job {job_id} completed. Found {len(items)} items.")

            return {
                "job_id": job_id,
                "status": "COMPLETED",
                "items": items,
                "raw_text": raw_text,
                "processing_time_ms": processing_time_ms
            }

        except Exception as e:
            logger.error(f"OCR job {job_id} failed: {e}")

            await self.ocr_jobs.update_one(
                {"job_id": job_id},
                {
                    "$set": {
                        "status": "FAILED",
                        "error": str(e),
                        "updated_at": datetime.utcnow()
                    }
                }
            )

            return {"job_id": job_id, "status": "FAILED", "error": str(e)}

    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get the status of an OCR job."""
        job = await self.ocr_jobs.find_one(
            {"job_id": job_id},
            {"_image_data": 0}  # Exclude image data
        )

        if not job:
            return None

        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "progress": self._get_progress(job["status"]),
            "error": job.get("error"),
            "created_at": job["created_at"],
            "updated_at": job["updated_at"]
        }

    async def get_job_result(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get the result of a completed OCR job."""
        job = await self.ocr_jobs.find_one(
            {"job_id": job_id},
            {"_image_data": 0}
        )

        if not job:
            return None

        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "items": job.get("items", []),
            "raw_text": job.get("raw_text"),
            "language_detected": job.get("language_detected"),
            "notes": job.get("notes"),
            "processing_time_ms": job.get("processing_time_ms"),
            "is_mock": job.get("is_mock", False)
        }

    async def get_matched_cart(
        self,
        job_id: str,
        store_id: str
    ) -> Dict[str, Any]:
        """
        Get OCR results matched to store products.

        Combines OCR extraction with inventory matching.
        """
        # Get OCR result
        job = await self.ocr_jobs.find_one({"job_id": job_id})
        if not job:
            return {"error": "Job not found"}

        if job["status"] != "COMPLETED":
            return {"error": f"Job not ready. Status: {job['status']}"}

        items = job.get("items", [])
        if not items:
            return {
                "job_id": job_id,
                "store_id": store_id,
                "matched": [],
                "unmatched": [],
                "cart_total": 0
            }

        # Match to store inventory
        inventory_service = InventoryService(self.db)
        match_result = await inventory_service.match_smart_cart(
            store_id,
            items
        )

        return {
            "job_id": job_id,
            "store_id": store_id,
            "ocr_items": items,
            "matched": [m.model_dump() for m in match_result.matched],
            "unmatched": match_result.unmatched,
            "suggestions": match_result.suggestions,
            "cart_total": match_result.cart_total
        }

    async def _preprocess_image(
        self,
        image_data: bytes,
        content_type: str
    ) -> tuple[bytes, str]:
        """
        Preprocess image for OCR.

        - Resize if too large
        - Enhance contrast
        - Convert to JPEG for consistency
        """
        try:
            # Open image with PIL
            image = Image.open(BytesIO(image_data))

            # Convert to RGB if necessary
            if image.mode != 'RGB':
                image = image.convert('RGB')

            # Resize if too large (max 2000px on longest side)
            max_size = 2000
            if max(image.size) > max_size:
                ratio = max_size / max(image.size)
                new_size = (int(image.size[0] * ratio), int(image.size[1] * ratio))
                image = image.resize(new_size, Image.Resampling.LANCZOS)

            # Optional: Enhance contrast for better OCR
            from PIL import ImageEnhance
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(1.2)  # Slight contrast boost

            # Convert to JPEG bytes
            output = BytesIO()
            image.save(output, format='JPEG', quality=85)
            processed_data = output.getvalue()

            return processed_data, "jpeg"

        except Exception as e:
            logger.warning(f"Image preprocessing failed: {e}. Using original.")
            # Determine format from content type
            format_map = {
                "image/jpeg": "jpeg",
                "image/png": "png",
                "image/webp": "webp"
            }
            image_format = format_map.get(content_type, "jpeg")
            return image_data, image_format

    def _get_progress(self, status: str) -> int:
        """Get progress percentage for status."""
        progress_map = {
            "PENDING": 0,
            "PROCESSING": 50,
            "COMPLETED": 100,
            "FAILED": 100
        }
        return progress_map.get(status, 0)


async def get_ocr_service(db: AsyncIOMotorDatabase) -> OCRService:
    """Get OCR service instance."""
    return OCRService(db)
