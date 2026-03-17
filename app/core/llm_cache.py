"""
LLM Intent-Based Cache
Canonical caching for LLM responses using structured intents — NOT raw text similarity.

Architecture:
  Tier 1: Exact match on normalized query text (O(1) hash lookup)
  Tier 2: Canonical intent hash — fast regex pre-classifier extracts
          {action, entity} → deterministic cache key (O(1) lookup)

Why NOT text similarity?
  "I want to cancel my order" and "I want to repeat my order" score
  near-identical on cosine/Jaccard but are opposite business actions.
  Intent-based keys make this impossible: cache:CANCEL:order ≠ cache:REPEAT:order

Works with Upstash Redis REST API — no RediSearch needed.
"""
import json
import hashlib
import re
import time
import logging
from typing import Optional, Any, Dict, Set

from app.db.redis import RedisClient
from app.config import settings

logger = logging.getLogger(__name__)


# ==================== Fast Intent Pre-Classifier ====================
# Extracts structured {action, entity} from common Hinglish patterns
# WITHOUT calling an LLM. Includes fuzzy matching, multi-intent detection,
# and entity normalization against the product catalog.

# Action keywords → canonical action name (exact targets for fuzzy match)
_ACTION_KEYWORDS: Dict[str, list] = {
    "add": [
        "add", "daal", "daalo", "lelo", "lena", "rakh", "rakho",
        "chahiye", "chaahiye", "laga", "lagao", "order", "mangwa", "bhej",
    ],
    "remove": [
        "remove", "hata", "hatao", "nikaal", "nikaalo", "cancel",
        "chhod", "chhodho", "chhoddo",
    ],
    "update": [
        "update", "change", "badal", "badlo", "badhao",
    ],
    "query": [
        "price", "batao", "dikhao", "dikha", "search", "dhundho", "show",
    ],
    "repeat": [
        "repeat", "dobara", "wapas",
    ],
}

# Regex patterns for multi-word action phrases (can't fuzzy-match these)
_ACTION_PHRASE_PATTERNS: Dict[str, list] = {
    "add": [r"\bdaal\s*do\b", r"\ble\s*lo\b", r"\ble\s*lunga\b"],
    "remove": [r"\bhata\s*do\b", r"\bnikaal\s*do\b", r"\bnahi\s*chahiye\b", r"\bmat\s*rakh\b"],
    "update": [r"\bkam\s*kar\b", r"\bzyada\s*kar\b"],
    "query": [r"\bkya\s*hai\b", r"\bkitne\s*ka\b", r"\bkitne\s*ki\b"],
    "repeat": [r"\bphir\s*se\b", r"\bfir\s*se\b"],
}

# Conjunctions that signal multi-intent queries
_MULTI_INTENT_SIGNALS = re.compile(
    r"\b(?:aur|and|bhi|sath|saath|plus|also|along\s*with)\b"
)

# Hinglish stopwords to strip before extracting entity (product name)
_ENTITY_STOPWORDS = frozenset({
    # Action words (already captured above)
    "add", "remove", "update", "change", "cancel", "repeat", "order", "search",
    "daal", "daalo", "hata", "hatao", "nikaal", "nikaalo", "badal", "badlo",
    "dikhao", "dikha", "batao", "dhundho", "show", "mangwa", "bhej",
    "karo", "kar", "kardo", "do", "de", "dedo", "rakh", "rakho", "laga", "lagao",
    # Pronouns/particles
    "mujhe", "mujhko", "mera", "mere", "merko", "hum", "humko",
    "aap", "aapka", "aapko", "tum", "tumko",
    "ye", "yeh", "wo", "woh", "isko", "usko", "inko", "unko",
    # Conjunctions/fillers
    "aur", "ya", "bhi", "sirf", "bas", "thoda", "bahut", "zyada", "kam",
    "chahiye", "chahte", "chaahiye", "lena", "leni", "lenge", "lunga",
    "hai", "hain", "ho", "tha", "the", "thi", "hoga",
    "ka", "ki", "ke", "ko", "se", "mein", "pe", "par", "tak",
    "ek", "do", "teen", "char", "paanch",
    "please", "bhai", "sir", "ji", "jaldi", "abhi", "ab",
    # Question/reasoning words
    "kya", "kaise", "kyun", "kab", "kahan", "kitna", "kitni", "kitne",
    "banane", "banana", "liye", "lagega", "lagta", "lagti",
    # Action modifiers
    "quantity", "qty", "price", "rate", "cost", "wala", "wali", "wale",
    "badhao", "badha", "double", "triple",
    # English fillers
    "the", "a", "an", "is", "are", "i", "want", "need", "my", "me",
    "to", "for", "of", "in", "on", "at", "with", "from", "and", "or",
    "can", "you", "some", "get", "give", "put", "make", "let",
    # Quantities
    "packet", "packets", "kg", "gram", "liter", "bottle", "piece", "pieces",
})


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Lightweight Levenshtein distance (no external deps)."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            curr_row.append(min(curr_row[j] + 1, prev_row[j + 1] + 1, prev_row[j] + cost))
        prev_row = curr_row
    return prev_row[-1]


def _fuzzy_match_action(word: str, max_distance: int = 1) -> Optional[str]:
    """
    Fuzzy-match a single word against all action keywords.
    Returns the canonical action name, or None if no close match.
    Allows `max_distance` character edits (default: 1 typo).
    """
    if len(word) < 3:
        return None  # Too short to fuzzy match reliably

    for action, keywords in _ACTION_KEYWORDS.items():
        for keyword in keywords:
            dist = _levenshtein_distance(word, keyword)
            # Allow 1 edit for words ≤5 chars, 2 edits for longer words
            allowed = max_distance if len(keyword) <= 5 else max_distance + 1
            if dist <= allowed:
                return action
    return None


def _detect_multi_intent(text: str) -> bool:
    """
    Detect if the query contains multiple intents separated by conjunctions.
    e.g., 'milk add karo aur bread cancel karo' → True
    """
    # Split on conjunction
    parts = _MULTI_INTENT_SIGNALS.split(text)
    if len(parts) < 2:
        return False

    # Check if at least 2 parts have independent action keywords
    action_count = 0
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Check for action words in this part
        words = part.split()
        for word in words:
            if _fuzzy_match_action(word, max_distance=0):
                action_count += 1
                break

    return action_count >= 2


def fast_extract_intent(text: str) -> Optional[Dict[str, str]]:
    """
    Fast intent extraction from Hinglish text with edge case handling.
    
    Returns {"action": "...", "entity": "..."} or None if:
      - Multi-intent detected (routes to LLM)
      - No entity could be extracted
      - Intent is ambiguous
    
    Features:
      - Fuzzy action matching (handles typos like 'ad' → 'add')
      - Multi-intent detection (splits compound queries)
      - Entity extraction with stopword removal
    """
    text_lower = text.strip().lower()

    # === GUARD: Multi-intent detection ===
    if _detect_multi_intent(text_lower):
        logger.info(f"🔀 Multi-intent detected, skipping cache: '{text[:60]}'")
        return None  # Force LLM fallback for compound queries

    # 1. Detect action — check exact regex phrases first, then fuzzy single words
    detected_action = None

    # 1a. Multi-word phrase patterns (exact regex, no fuzzy)
    for action, patterns in _ACTION_PHRASE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                detected_action = action
                break
        if detected_action:
            break

    # 1b. Single-word fuzzy matching (handles typos)
    if not detected_action:
        words = re.sub(r"[^\w\s]", "", text_lower).split()
        for word in words:
            matched_action = _fuzzy_match_action(word, max_distance=1)
            if matched_action:
                detected_action = matched_action
                break

    if not detected_action:
        detected_action = "query"  # Default for bare product names

    # 2. Extract entity (product name) by stripping all stopwords
    words = re.sub(r"[^\w\s]", "", text_lower).split()
    entity_words = [w for w in words if w not in _ENTITY_STOPWORDS and len(w) > 1 and not w.isdigit()]
    entity = " ".join(entity_words) if entity_words else ""

    if not entity:
        return None

    return {
        "action": detected_action,
        "entity": entity,
    }


def normalize_entity_to_catalog(
    entity: str,
    available_products: list,
    threshold: float = 0.65,
) -> str:
    """
    Map a raw extracted entity to the best-matching product name in the catalog.
    Solves the granularity problem:
      - 'amul taaza double toned milk 500ml' → 'Amul Taaza Toned Milk' (catalog name)
      - 'cofee' → 'Coffee' (corrects typo via fuzzy match)
    
    Returns the catalog product name if a good match is found,
    otherwise returns the original entity (for new/unknown products).
    """
    from difflib import SequenceMatcher

    if not entity or not available_products:
        return entity

    entity_lower = entity.lower()
    best_name = entity
    best_score = 0.0

    for product in available_products:
        prod_name = product.get("name", "")
        if not prod_name:
            continue
        prod_lower = prod_name.lower()

        # Full string similarity
        full_sim = SequenceMatcher(None, entity_lower, prod_lower).ratio()

        # Word-level matching: each entity word against product words
        entity_words = entity_lower.split()
        prod_words = prod_lower.split()
        word_hits = 0
        for ew in entity_words:
            if len(ew) < 2:
                continue
            for pw in prod_words:
                if len(pw) < 2:
                    continue
                if SequenceMatcher(None, ew, pw).ratio() > 0.75:
                    word_hits += 1
                    break

        word_sim = word_hits / max(len(entity_words), 1)

        # Combined score (word matching is more important for partial names)
        score = 0.4 * full_sim + 0.6 * word_sim

        if score > best_score:
            best_score = score
            best_name = prod_name

    if best_score >= threshold:
        logger.debug(f"🎯 Entity normalized: '{entity}' → '{best_name}' (score: {best_score:.2f})")
        return best_name.lower()

    return entity


# ==================== Opposite Intent Detection ====================

_OPPOSITE_ACTIONS = {
    ("add", "remove"), ("remove", "add"),
    ("add", "cancel"), ("cancel", "add"),
    ("repeat", "cancel"), ("cancel", "repeat"),
}


def _are_opposite_intents(intent_a: Dict, intent_b: Dict) -> bool:
    """Check if two intents are business-logic opposites."""
    pair = (intent_a.get("action", ""), intent_b.get("action", ""))
    return pair in _OPPOSITE_ACTIONS


# ==================== LLM Cache ====================

class LLMCache:
    """
    Intent-based LLM response cache.
    
    Tier 1: Exact match on normalized query hash (catches identical repetitions)
    Tier 2: Canonical intent hash — fast regex extracts {action, entity},
            hashes to O(1) key like `llm_intent:intent:add:coffee`
    
    Namespaces isolate different services (intent, agent, nudge, route).
    """

    def __init__(self):
        self.enabled = settings.LLM_CACHE_ENABLED
        self.max_scan_entries = settings.LLM_CACHE_MAX_ENTRIES
        self._stats = {"hits_exact": 0, "hits_intent": 0, "misses": 0, "clashes_blocked": 0}

    # ==================== Public API ====================

    async def get(
        self,
        query: str,
        namespace: str,
        context_hash: str = "",
        available_products: list = None,
    ) -> Optional[Any]:
        """
        Two-tier cache lookup: exact text → canonical intent.
        
        Args:
            available_products: Product catalog for entity normalization.
                                Resolves 'cofee' → 'coffee' (catalog name).
        
        Returns cached response dict, or None on miss.
        """
        if not self.enabled:
            return None

        # --- Tier 1: Exact match (O(1) hash of normalized text) ---
        exact_key = self._exact_key(query, namespace, context_hash)
        try:
            raw = await RedisClient.get(exact_key)
            if raw:
                entry = json.loads(raw)
                self._stats["hits_exact"] += 1
                logger.info(f"⚡ LLM Cache EXACT HIT [{namespace}]: '{query[:60]}'")
                return entry.get("response")
        except Exception as e:
            logger.warning(f"LLM cache exact-get error: {e}")

        # --- Tier 2: Canonical intent hash (O(1) lookup) ---
        try:
            intent = fast_extract_intent(query)
            if intent:
                # Normalize entity against catalog if available
                if available_products:
                    intent["entity"] = normalize_entity_to_catalog(
                        intent["entity"], available_products
                    )
                intent_key = self._intent_key(intent, namespace, context_hash)
                raw = await RedisClient.get(intent_key)
                if raw:
                    entry = json.loads(raw)
                    cached_intent = entry.get("intent", {})

                    # SAFETY: Block opposite intent clashes
                    if _are_opposite_intents(intent, cached_intent):
                        self._stats["clashes_blocked"] += 1
                        logger.warning(
                            f"🛑 LLM Cache CLASH BLOCKED [{namespace}]: "
                            f"query='{query[:40]}' intent={intent['action']}:{intent['entity']} "
                            f"vs cached={cached_intent.get('action')}:{cached_intent.get('entity')}"
                        )
                        return None

                    self._stats["hits_intent"] += 1
                    logger.info(
                        f"🎯 LLM Cache INTENT HIT [{namespace}]: "
                        f"'{query[:40]}' → {intent['action']}:{intent['entity']}"
                    )
                    return entry.get("response")
        except Exception as e:
            logger.warning(f"LLM cache intent-get error: {e}")

        self._stats["misses"] += 1
        return None

    async def set(
        self,
        query: str,
        namespace: str,
        response: Any,
        context_hash: str = "",
        ttl: int = None,
        available_products: list = None,
    ) -> bool:
        """
        Cache an LLM response with both exact-match key and canonical intent key.
        
        Args:
            available_products: Product catalog for entity normalization.
        """
        if not self.enabled:
            return False

        ttl = ttl or settings.LLM_CACHE_EXACT_TTL

        try:
            intent = fast_extract_intent(query)

            # Normalize entity against catalog if available
            if intent and available_products:
                intent["entity"] = normalize_entity_to_catalog(
                    intent["entity"], available_products
                )

            entry = {
                "query": query,
                "response": response,
                "intent": intent,  # Stored for clash detection on retrieval
                "timestamp": time.time(),
                "namespace": namespace,
            }
            serialized = json.dumps(entry, default=str)

            # --- Store exact-match entry ---
            exact_key = self._exact_key(query, namespace, context_hash)
            await RedisClient.setex(exact_key, ttl, serialized)

            # --- Store intent-based entry ---
            if intent:
                intent_key = self._intent_key(intent, namespace, context_hash)
                await RedisClient.setex(intent_key, ttl, serialized)

            logger.info(
                f"💾 LLM Cache SET [{namespace}]: '{query[:40]}' "
                f"intent={intent['action'] + ':' + intent['entity'] if intent else 'none'} "
                f"(TTL: {ttl}s)"
            )
            return True

        except Exception as e:
            logger.warning(f"LLM cache set error: {e}")
            return False

    async def invalidate_namespace(self, namespace: str, context_hash: str = "") -> int:
        """Invalidate all cached entries for a specific namespace+context."""
        # Note: Without key scanning (Upstash limitation), we can't bulk-delete
        # by prefix. Individual keys expire via TTL. This method invalidates
        # known keys if tracked.
        logger.info(f"🗑️ LLM Cache namespace '{namespace}' will expire via TTL")
        return 0

    def get_stats(self) -> dict:
        """Return cache hit/miss/clash statistics."""
        total = self._stats["hits_exact"] + self._stats["hits_intent"] + self._stats["misses"]
        hit_rate = (
            (self._stats["hits_exact"] + self._stats["hits_intent"]) / total * 100
            if total > 0
            else 0
        )
        return {
            **self._stats,
            "total_lookups": total,
            "hit_rate_percent": round(hit_rate, 1),
        }

    # ==================== Private Helpers ====================

    def _exact_key(self, query: str, namespace: str, context_hash: str) -> str:
        """Exact-match cache key from normalized query text."""
        normalized = self._normalize_query(query)
        query_hash = hashlib.sha256(normalized.encode()).hexdigest()[:20]
        return f"llm_exact:{namespace}:{context_hash}:{query_hash}"

    @staticmethod
    def _intent_key(intent: Dict[str, str], namespace: str, context_hash: str) -> str:
        """
        Canonical intent cache key.
        e.g., "llm_intent:intent:abc123:add:coffee"
        
        Same action + same entity → same key, regardless of phrasing.
        """
        action = intent.get("action", "unknown")
        entity = intent.get("entity", "").strip()
        # Normalize entity: lowercase, sort words alphabetically for consistency
        entity_normalized = " ".join(sorted(entity.lower().split()))
        return f"llm_intent:{namespace}:{context_hash}:{action}:{entity_normalized}"

    @staticmethod
    def _normalize_query(text: str) -> str:
        """Normalize query for exact-match deduplication."""
        text = text.lower().strip()
        text = re.sub(r"[^\w\s]", "", text)
        text = re.sub(r"\s+", " ", text)
        return text


# ==================== Singleton ====================

_llm_cache: Optional[LLMCache] = None


def get_llm_cache() -> LLMCache:
    """Get the singleton LLM cache instance."""
    global _llm_cache
    if _llm_cache is None:
        _llm_cache = LLMCache()
    return _llm_cache
