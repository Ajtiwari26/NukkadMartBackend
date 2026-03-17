"""
Agent Orchestrator
Agentic LLM shopping assistant using AWS Bedrock Converse API with function calling.
Transforms NukkadMart voice queries into multi-step reasoning + tool execution.

Architecture:
  User query → Bedrock (with tools) → toolUse → execute → toolResult → loop
                                    ↘ Final text response → AgentResponse
"""
import os
import json
import logging
import asyncio
import hashlib
from typing import Dict, List, Optional

import boto3

from app.models.agent_models import AgentResponse, SuggestedItem
from app.services.agent_tools import AgentToolExecutor
from app.core.llm_cache import get_llm_cache

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool schema definitions sent to Bedrock Converse API
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "toolSpec": {
            "name": "search_products",
            "description": (
                "Search for products in the customer's store inventory. "
                "If no results are found in the current store, this tool AUTOMATICALLY "
                "searches all nearby stores too — so you always get the best match. "
                "Returns a list of matching products with names, prices, stock, and store info."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Product name or description to search for (in English)"
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results to return (default 5)",
                            "default": 5
                        },
                        "category_filter": {
                            "type": "string",
                            "description": "Optional category to filter by (e.g. 'Spices', 'Dairy')"
                        }
                    },
                    "required": ["query"]
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "search_nearby_stores",
            "description": (
                "Search other nearby stores when a product is not found in the primary store. "
                "Only call this if search_products returned no results or the product is out of stock."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Product name to search for"
                        },
                        "brand": {
                            "type": "string",
                            "description": "Optional brand preference"
                        }
                    },
                    "required": ["query"]
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "get_recipe_ingredients",
            "description": (
                "Use this when a user wants to cook a dish and needs to know the ingredients. "
                "You already know the recipe — call this tool to list the ingredients you identified, "
                "then search for each one."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "dish_name": {
                            "type": "string",
                            "description": "Name of the dish (e.g. 'Pav Bhaji', 'Dal Tadka')"
                        },
                        "ingredients": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of ingredient names you identified for this dish"
                        },
                        "user_has": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Ingredients the user said they already have"
                        }
                    },
                    "required": ["dish_name", "ingredients"]
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "get_cart_contents",
            "description": "Get the current contents of the shopping cart. Use this to check what the user already has.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    }
]


# ---------------------------------------------------------------------------
# System Prompt (the "grandmother" persona)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a wise, caring shopping assistant for NukkadMart — a local grocery delivery app in India.

Think of yourself as an experienced dadi/nani (grandmother) who knows every recipe and household trick. You speak in simple, warm Hinglish and address the customer as "Sir" or "Ji".

YOUR BEHAVIOUR:
1. When a user asks for a dish or has a problem, figure out what items they need.
2. Use search_products to find items — search ALL ingredients in a SINGLE turn (call search_products multiple times in parallel).
3. After searching, respond with your final JSON including ONLY the items that WERE found.
4. Do NOT mention items that were not found. Do NOT say "cardamom nahi mila" or "saffron available nahi hai". Just silently skip missing items.
5. Keep your message extremely short — just say what you found, nothing else.

CRITICAL: You have a MAXIMUM of 3 turns. Ideal flow:
  Turn 1: get_recipe_ingredients (if recipe) + search_products for ALL items
  Turn 2: Final JSON with found items ONLY
search_products automatically searches nearby stores if item is not in the current store.

RESPONSE FORMAT:
Respond with valid JSON only (no markdown, no code blocks):
{
  "message": "Short Hinglish message — ONLY mention what was found, never mention missing items",
  "suggested_items": [
    {"item_id": "PRODUCT_ID", "name": "Product Name", "shop_id": "STORE_ID", "price": 0, "brand": "...", "unit": "...", "store_name": "Store Name"}
  ],
  "action_required": "confirm_add_to_cart",
  "reasoning": "brief internal note"
}

RULES:
- Always search before responding — never suggest items from memory alone.
- ONLY include items that search_products actually returned results for.
- NEVER mention unavailable/missing items in "message". Silently skip them.
- Keep message to 1 short sentence max — it will be spoken via TTS.
- Use real product_id and store_id from search results.
- Always include store_name from search results so the UI can show which store.
- action_required should be "confirm_add_to_cart" for recipes/multi-item results.
"""


# ---------------------------------------------------------------------------
# Agent Orchestrator
# ---------------------------------------------------------------------------

class AgentOrchestrator:
    """
    Agentic LLM orchestrator using AWS Bedrock Converse API with tool_use.

    Flow:
      1. Build messages with system prompt + user query
      2. Call Bedrock Converse (with tool definitions)
      3. If response contains toolUse blocks → execute each tool → append toolResult → repeat
      4. When response is final text → parse JSON → return AgentResponse
    """

    MAX_TURNS = 3   # Hard cap: prevents runaway tool loops (search→fail→search→...) 
    MODEL_ID = "apac.amazon.nova-pro-v1:0"

    def __init__(self):
        region = os.getenv("AWS_REGION", "ap-south-1")
        self._bedrock = boto3.client("bedrock-runtime", region_name=region)
        self.llm_cache = get_llm_cache()

    async def process_query(
        self,
        user_text: str,
        tool_executor: AgentToolExecutor,
        conversation_history: Optional[List[Dict]] = None,
    ) -> AgentResponse:
        """
        Entry point: process a complex user query through the agentic loop.

        Args:
            user_text:            Transcribed user speech (English/Hinglish)
            tool_executor:        AgentToolExecutor bound to current session context
            conversation_history: Optional multi-turn history (list of {role, content})

        Returns:
            AgentResponse with message + suggested_items
        """
        # === LLM CACHE: Check for cached agent response ===
        # Context hash includes store products for isolation
        ctx_hash = ""
        if tool_executor and hasattr(tool_executor, 'current_store_id'):
            ctx_hash = hashlib.md5((tool_executor.current_store_id or "").encode()).hexdigest()[:12]

        cached = await self.llm_cache.get(user_text, "agent", ctx_hash)
        if cached:
            logger.info(f"⚡ LLM Cache HIT for agent query: '{user_text[:60]}'")
            # Reconstruct AgentResponse from cached dict
            suggested_items = []
            for item_data in cached.get("suggested_items", []):
                try:
                    suggested_items.append(SuggestedItem(**item_data))
                except Exception:
                    pass
            return AgentResponse(
                message=cached.get("message", ""),
                suggested_items=suggested_items,
                action_required=cached.get("action_required", "info_only"),
                reasoning=cached.get("reasoning", "cached response"),
            )
        # === End LLM Cache check ===

        messages = list(conversation_history or [])
        messages.append({
            "role": "user",
            "content": [{"text": user_text}]
        })

        for turn in range(self.MAX_TURNS):
            response = await self._call_bedrock(messages)
            output_message = response.get("output", {}).get("message", {})
            stop_reason = response.get("stopReason", "end_turn")

            # Append assistant message to history
            messages.append({
                "role": "assistant",
                "content": output_message.get("content", [])
            })

            if stop_reason == "tool_use":
                # Execute all tool calls in parallel and collect results
                tool_results = await self._execute_tool_calls(
                    output_message.get("content", []),
                    tool_executor
                )

                # Append tool results as user message
                messages.append({
                    "role": "user",
                    "content": tool_results
                })
                logger.info(f"🔄 Agent turn {turn + 1}/{self.MAX_TURNS}: executed {len(tool_results)} tool(s)")

            elif stop_reason in ("end_turn", "max_tokens"):
                # Final response — extract text and parse JSON
                final_text = self._extract_text(output_message.get("content", []))
                logger.info(f"✅ Agent final response (turn {turn + 1}): {final_text[:120]}...")
                agent_response = self._parse_response(final_text)

                # === LLM CACHE: Store agent response ===
                cache_entry = {
                    "message": agent_response.message,
                    "suggested_items": [
                        {"item_id": si.item_id, "name": si.name, "shop_id": si.shop_id,
                         "price": si.price, "brand": si.brand, "unit": si.unit,
                         "store_name": si.store_name, "stock": si.stock, "category": si.category}
                        for si in (agent_response.suggested_items or [])
                    ],
                    "action_required": agent_response.action_required,
                    "reasoning": agent_response.reasoning,
                }
                await self.llm_cache.set(user_text, "agent", cache_entry, ctx_hash, ttl=3600)
                # === End LLM Cache store ===

                return agent_response

            else:
                logger.warning(f"Unexpected stopReason: {stop_reason} — stopping agent loop")
                break

        # Loop exhausted without final response — salvage products from tool results
        logger.error(f"Agent hit MAX_TURNS ({self.MAX_TURNS}) without end_turn — salvaging found products")
        return self._salvage_from_history(messages)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _call_bedrock(self, messages: List[Dict]) -> Dict:
        """Call Bedrock Converse API in a thread pool (boto3 is sync)."""
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._bedrock.converse(
                modelId=self.MODEL_ID,
                system=[{"text": SYSTEM_PROMPT}],
                messages=messages,
                toolConfig={"tools": TOOL_DEFINITIONS},
                inferenceConfig={
                    "maxTokens": 1024,
                    "temperature": 0.3,
                }
            )
        )
        return response

    async def _execute_tool_calls(
        self, content_blocks: List[Dict], tool_executor: AgentToolExecutor
    ) -> List[Dict]:
        """Execute all toolUse blocks in the content, return toolResult blocks."""
        tool_result_blocks = []

        for block in content_blocks:
            if "toolUse" not in block:
                continue

            tool_use = block["toolUse"]
            tool_id = tool_use["toolUseId"]
            tool_name = tool_use["name"]
            tool_input = tool_use.get("input", {})

            result = await tool_executor.execute(tool_name, tool_input)

            tool_result_blocks.append({
                "toolResult": {
                    "toolUseId": tool_id,
                    "content": [{"json": result}]
                }
            })

        return tool_result_blocks

    def _extract_text(self, content_blocks: List[Dict]) -> str:
        """Concatenate all text blocks from a message content."""
        parts = []
        for block in content_blocks:
            if "text" in block:
                parts.append(block["text"])
        return " ".join(parts).strip()

    def _parse_response(self, text: str) -> AgentResponse:
        """
        Parse the LLM's final text output into an AgentResponse.
        The LLM is instructed to respond with raw JSON — but we handle
        cases where it adds markdown fences or extra prose.
        """
        import re

        # Strip markdown code fences if present
        cleaned = re.sub(r"```(?:json)?", "", text).strip()

        # Try to find a JSON object in the text
        json_match = re.search(r"\{[\s\S]*\}", cleaned)
        if not json_match:
            logger.warning("No JSON found in agent response, building fallback")
            return AgentResponse(
                message=text[:300],  # Use raw text as message
                action_required="info_only",
            )

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse agent JSON: {e}")
            return AgentResponse(
                message=text[:300],
                action_required="info_only",
            )

        # Build SuggestedItem list
        suggested_items = []
        for raw in data.get("suggested_items", []):
            try:
                suggested_items.append(SuggestedItem(
                    item_id=str(raw.get("item_id", raw.get("product_id", ""))),
                    name=raw.get("name", ""),
                    shop_id=str(raw.get("shop_id", raw.get("store_id", ""))),
                    price=float(raw.get("price", 0)),
                    brand=raw.get("brand"),
                    unit=raw.get("unit"),
                    store_name=raw.get("store_name"),
                    stock=raw.get("stock"),
                    category=raw.get("category"),
                ))
            except Exception as e:
                logger.warning(f"Skipping malformed suggested_item: {raw} — {e}")

        action = data.get("action_required", "info_only")
        if action not in ("confirm_add_to_cart", "select_variant", "info_only", "needs_clarification"):
            action = "confirm_add_to_cart" if suggested_items else "info_only"

        return AgentResponse(
            message=data.get("message", text[:200]),
            suggested_items=suggested_items,
            action_required=action,
            reasoning=data.get("reasoning"),
        )

    def _salvage_from_history(self, messages: List[Dict]) -> AgentResponse:
        """
        When MAX_TURNS is hit, scan tool results for products found during
        searches and return them as a proper AgentResponse instead of losing them.
        """
        found_products = {}  # keyed by product_id to de-duplicate
        assistant_texts = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", [])

            # Collect any assistant text for message fallback
            if role == "assistant":
                for block in content:
                    if "text" in block:
                        assistant_texts.append(block["text"])

            # Scan toolResult blocks for search results
            if role == "user":
                for block in content:
                    tool_result = block.get("toolResult")
                    if not tool_result:
                        continue
                    for result_content in tool_result.get("content", []):
                        json_data = result_content.get("json", {})
                        results = json_data.get("results", [])
                        for product in results:
                            pid = product.get("product_id", "")
                            if pid and pid not in found_products:
                                found_products[pid] = product

        if not found_products:
            logger.info("No products salvaged from tool history — returning clarification")
            return AgentResponse(
                message="Sir, thoda sa confusion ho gayi. Kya aap dobara bata sakte hain?",
                action_required="needs_clarification",
            )

        # Build SuggestedItem list from salvaged products
        suggested_items = []
        for product in found_products.values():
            try:
                suggested_items.append(SuggestedItem(
                    item_id=str(product.get("product_id", "")),
                    name=product.get("name", ""),
                    shop_id=str(product.get("store_id", "")),
                    price=float(product.get("price", 0)),
                    brand=product.get("brand"),
                    unit=product.get("unit"),
                    store_name=product.get("store_name"),
                    stock=product.get("stock"),
                    category=product.get("category"),
                ))
            except Exception as e:
                logger.warning(f"Skipping salvaged product: {product} — {e}")

        # Build a message — prefer assistant text if available
        message = "Sir, ye products mil gaye aapke liye. Confirm karein toh cart mein daal doon?"
        if assistant_texts:
            # Use the last meaningful assistant text (often the best summary)
            last_text = assistant_texts[-1].strip()
            if len(last_text) > 10:
                message = last_text[:300]

        logger.info(f"🔧 Salvaged {len(suggested_items)} products from MAX_TURNS overflow")
        return AgentResponse(
            message=message,
            suggested_items=suggested_items,
            action_required="confirm_add_to_cart",
            reasoning="Salvaged from tool results after MAX_TURNS exceeded",
        )


# ---------------------------------------------------------------------------
# Singleton + LLM-based query classifier
# ---------------------------------------------------------------------------

_orchestrator: Optional[AgentOrchestrator] = None


def get_agent_orchestrator() -> AgentOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AgentOrchestrator()
    return _orchestrator


# Short prompt for the routing LLM call — Nova Pro (fast, cheap)
_ROUTING_SYSTEM = """You are a query classifier. Reply with exactly ONE word: 'agent' or 'fast'.

'fast'  = simple product add/update/remove/search (single product, clear intent)
'agent' = anything else: multi-product, recipe, dish name, household problem/tip, health question, vague need

Examples:
"ek coffee daal do" -> fast
"mirchi ka packet lena hai" -> fast
"remove milk from cart" -> fast
"pav bhaji banani hai" -> agent
"mera gala kharab hai, kya lu" -> agent
"shirt pe daag hai" -> agent
"nashte ke liye kya chahiye" -> agent
"chai aur biscuit" -> agent
"aloo tamatar pyaz chahiye" -> agent
"""


async def should_use_agent(user_text: str) -> bool:
    """
    LLM-based router: decides whether a query needs the full agent (True)
    or can be handled by the existing fast-path intent classifier (False).

    Uses a tiny single-turn Bedrock call (no tools). Falls back to the
    heuristic if the LLM call fails so the system is always resilient.
    """
    import asyncio
    import boto3
    import os

    try:
        # === LLM CACHE: Check cached routing decision ===
        llm_cache = get_llm_cache()
        cached_route = await llm_cache.get(user_text, "route")
        if cached_route is not None:
            result = cached_route.get("is_agent", False)
            logger.info(f"⚡ Route Cache HIT for '{user_text[:60]}': {'AGENT' if result else 'FAST'}")
            return result
        # === End cache check ===

        region = os.getenv("AWS_REGION", "ap-south-1")
        bedrock = boto3.client("bedrock-runtime", region_name=region)
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: bedrock.converse(
                modelId="apac.amazon.nova-pro-v1:0",
                system=[{"text": _ROUTING_SYSTEM}],
                messages=[{"role": "user", "content": [{"text": user_text}]}],
                inferenceConfig={"maxTokens": 5, "temperature": 0.0},
            )
        )
        answer = (
            response.get("output", {})
            .get("message", {})
            .get("content", [{}])[0]
            .get("text", "")
            .strip()
            .lower()
        )
        result = answer.startswith("agent")
        logger.info(f"🗺️  Route decision for '{user_text[:60]}': {'AGENT' if result else 'FAST'} (LLM said: {answer!r})")

        # === LLM CACHE: Store routing decision ===
        await llm_cache.set(user_text, "route", {"is_agent": result}, ttl=7200)  # 2 hour TTL for routing
        # === End cache store ===

        return result

    except Exception as e:
        logger.warning(f"LLM router failed, falling back to heuristic: {e}")
        return _heuristic_should_use_agent(user_text)


def _heuristic_should_use_agent(user_text: str) -> bool:
    """Keyword heuristic fallback — only used if the LLM router call fails."""
    text_lower = user_text.strip().lower()

    # Very short queries are almost always simple
    if len(text_lower.split()) <= 3:
        return False

    AGENT_SIGNALS = [
        # Cooking / recipes
        "banana", "banani", "banane", "recipe", "dish", "khana", "cook",
        "pav bhaji", "biryani", "pulao", "khichdi", "dal", "sabzi",
        # Household problem
        "daag", "stain", "clean", "saaf", "hatana", "kaise", "help",
        "gala", "kharab", "takleef", "problem", "bimari", "dawa",
        # Open question / suggestions
        "recommend", "suggest", "chahiye kya", "kya lu", "kya lun",
        "kya karun", "batao",
    ]
    if any(sig in text_lower for sig in AGENT_SIGNALS):
        return True

    # Multiple items (>=2 conjunction signals)
    LIST_SIGNALS = ["aur", "sath", "bhi", "along", "list", "sab", "kuch", "aadi"]
    if sum(1 for s in LIST_SIGNALS if s in text_lower) >= 2:
        return True

    return False
