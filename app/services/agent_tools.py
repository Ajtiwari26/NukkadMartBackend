"""
Agent Tools
Thin wrappers around existing NukkadMart services, exposed as callable functions
for the AgentOrchestrator's tool-use loop.

Each function corresponds to a Bedrock tool definition and returns a dict
that is sent back to the LLM as a `toolResult`.
"""
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool executor registry
# ---------------------------------------------------------------------------

class AgentToolExecutor:
    """
    Executes tool calls dispatched by the AgentOrchestrator.
    Wraps existing services so the orchestrator stays agnostic of internals.
    """

    def __init__(
        self,
        context_products: List[Dict],
        session_cart: Dict[str, float],
        session_id: str,
        current_store_id: Optional[str] = None,
    ):
        self.context_products = context_products
        self.session_cart = session_cart
        self.session_id = session_id
        self.current_store_id = current_store_id

    async def execute(self, tool_name: str, tool_input: Dict) -> Dict:
        """Dispatch a tool call and return its result as a serialisable dict."""
        logger.info(f"🔧 Agent tool call: {tool_name}({tool_input})")

        dispatch = {
            "search_products": self._search_products,
            "search_nearby_stores": self._search_nearby_stores,
            "get_recipe_ingredients": self._get_recipe_ingredients,
            "get_cart_contents": self._get_cart_contents,
        }

        handler = dispatch.get(tool_name)
        if not handler:
            logger.warning(f"Unknown tool: {tool_name}")
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            return await handler(tool_input)
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}")
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    async def _search_products(self, params: Dict) -> Dict:
        """
        Search products in the current session context (Redis-cached inventory).
        Uses existing HybridSearchService (BM25 + vector + fuzzy).
        
        AUTO-FALLBACK: If no results found in current store, automatically
        searches nearby stores so recipe ingredient searches work cross-shop.
        """
        from app.services.search_service import get_search_service

        query = params.get("query", "")
        max_results = min(params.get("max_results", 10), 20)
        category_filter = params.get("category_filter")

        if not query:
            return {"results": [], "count": 0}

        results = []
        
        # Step 1: Search current store's context_products
        if self.context_products:
            search_service = get_search_service()
            scored = search_service.search(
                query=query,
                products=self.context_products,
                limit=max_results,
                keyword_weight=0.3,
                vector_weight=0.6,
                fuzzy_weight=0.1,
                min_score=0.15,
            )

            for score, product in scored:
                if category_filter and product.get("category", "").lower() != category_filter.lower():
                    continue
                results.append({
                    "product_id": product.get("id", product.get("_id", "")),
                    "name": product.get("name", ""),
                    "brand": product.get("brand", ""),
                    "price": product.get("price", 0),
                    "unit": product.get("weight", product.get("unit", "")),
                    "stock": product.get("stock", 0),
                    "category": product.get("category", ""),
                    "store_id": product.get("store_id", self.current_store_id or ""),
                    "store_name": product.get("store_name", ""),
                    "score": round(score, 3),
                })

        # Step 2: AUTO-FALLBACK — if nothing found in current store, search nearby stores
        if not results:
            logger.info(f"🔄 No results in current store for '{query}', auto-searching nearby stores...")
            nearby_results = await self._search_nearby_stores({"query": query})
            nearby_items = nearby_results.get("results", [])
            
            for item in nearby_items:
                item["from_other_store"] = True
                results.append(item)

        logger.info(f"🔍 search_products('{query}') → {len(results)} results")
        return {"results": results, "count": len(results)}

    async def _search_nearby_stores(self, params: Dict) -> Dict:
        """
        Search across nearby / demo stores for a product not found in the
        primary store. Uses existing VoiceContextService.search_across_demo_stores().
        """
        from app.services.voice_context_service import VoiceContextService

        query = params.get("query", "")
        brand = params.get("brand")
        exclude_store_id = params.get("exclude_store_id", self.current_store_id)

        if not query:
            return {"results": [], "count": 0}

        ctx_service = VoiceContextService()
        matches = await ctx_service.search_across_demo_stores(query, brand)

        # Exclude current store to avoid duplicates
        if exclude_store_id:
            matches = [m for m in matches if m.get("store_id") != exclude_store_id]

        results = [
            {
                "product_id": m.get("id", m.get("_id", "")),
                "name": m.get("name", ""),
                "brand": m.get("brand", ""),
                "price": m.get("price", 0),
                "unit": m.get("weight", m.get("unit", "")),
                "stock": m.get("stock", 0),
                "store_id": m.get("store_id", ""),
                "store_name": m.get("store_name", ""),
            }
            for m in matches[:10]
        ]

        logger.info(f"🏪 search_nearby_stores('{query}') → {len(results)} results")
        return {"results": results, "count": len(results)}

    async def _get_recipe_ingredients(self, params: Dict) -> Dict:
        """
        Returns known ingredients for a dish.
        The LLM already knows recipes natively — this tool exists so the agent
        can express its knowledge in a structured format and then search for each item.

        Returns a list of ingredient strings that the agent should search for.
        """
        dish_name = params.get("dish_name", "")
        # The LLM fills in `ingredients` itself via system prompt guidance.
        # We just pass through and let the caller search for each ingredient.
        ingredients = params.get("ingredients", [])

        logger.info(f"🍳 get_recipe_ingredients('{dish_name}') → {len(ingredients)} ingredients")
        return {
            "dish": dish_name,
            "ingredients": ingredients,
            "note": "Search for each ingredient using search_products",
        }

    async def _get_cart_contents(self, params: Dict) -> Dict:
        """Return the current session cart as a readable list."""
        cart_items = []
        for product in self.context_products:
            pid = str(product.get("id", product.get("_id", "")))
            qty = self.session_cart.get(pid, 0)
            if qty > 0:
                cart_items.append({
                    "product_id": pid,
                    "name": product.get("name", ""),
                    "quantity": qty,
                    "price": product.get("price", 0),
                    "store_id": product.get("store_id", ""),
                })

        return {
            "items": cart_items,
            "total_items": len(cart_items),
            "is_empty": len(cart_items) == 0,
        }
