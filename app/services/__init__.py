# Services module - Business logic layer

from .inventory_service import InventoryService
from .ai_service import AIService, get_ai_service, bedrock_service, get_bedrock_service
from .ocr_service import OCRService
from .nudge_service import NudgeService

__all__ = [
    "InventoryService",
    "AIService",
    "get_ai_service",
    # Backward compatibility aliases
    "bedrock_service",
    "get_bedrock_service",
    "OCRService",
    "NudgeService"
]
