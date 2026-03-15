"""
Agent Response Models
Structured Pydantic models for the agentic LLM shopping assistant responses.
"""
from typing import Optional, List, Literal
from pydantic import BaseModel


class SuggestedItem(BaseModel):
    """A product item suggested by the agent"""
    item_id: str
    name: str
    shop_id: str
    price: float
    store_name: Optional[str] = None
    brand: Optional[str] = None
    unit: Optional[str] = None
    stock: Optional[int] = None
    category: Optional[str] = None


class AgentResponse(BaseModel):
    """
    Structured response from the AgentOrchestrator.
    Contains the friendly message + list of suggested items to show in UI.
    """
    message: str
    """Friendly 'grandmother' style explanation spoken via TTS"""

    suggested_items: List[SuggestedItem] = []
    """Products to display in the product_selection UI panel"""

    action_required: Literal["confirm_add_to_cart", "info_only", "select_variant", "needs_clarification"] = "info_only"
    """
    confirm_add_to_cart: Show items with 'Add All' button
    select_variant:      Show items, user picks one
    info_only:           Just informational response, no cart action
    needs_clarification: Ask user a follow-up question
    """

    reasoning: Optional[str] = None
    """Internal reasoning trace (for logging/debugging only)"""

    def to_product_selection_event(self, product_name: str = "Suggestions") -> dict:
        """
        Convert to the existing `product_selection` WebSocket event format
        so the existing Flutter bottom sheet UI can render the items.
        """
        options = [
            {
                "product_id": item.item_id,
                "name": item.name,
                "brand": item.brand,
                "price": item.price,
                "unit": item.unit,
                "in_cart": 0,
                "store_id": item.shop_id,
            }
            for item in self.suggested_items
        ]
        return {
            "event": "product_selection",
            "product_name": product_name,
            "action": "add",
            "quantity": 1,
            "options": options,
            "agent_message": self.message,        # Pass-through for frontend display
            "action_required": self.action_required,
        }
