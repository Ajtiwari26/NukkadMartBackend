"""
Hybrid Search Service
Combines keyword-based (BM25-like) scoring with vector similarity (Titan embeddings)
for accurate product search. No external search engine needed — uses MongoDB + numpy.
"""
import math
import logging
from typing import List, Dict, Optional, Tuple
from difflib import SequenceMatcher

from app.services.embedding_service import get_embedding_service

logger = logging.getLogger(__name__)


# Multilingual product alias map (Hindi/Hinglish → English)
PRODUCT_ALIASES = {
    # Dairy
    'doodh': 'milk', 'dudh': 'milk',
    'dahi': 'curd', 'dahee': 'curd',
    'makhan': 'butter', 'makkhan': 'butter',
    'paneer': 'paneer', 'panir': 'paneer',
    'ghee': 'ghee', 'ghi': 'ghee',
    # Grains & Staples
    'chawal': 'rice', 'chaawal': 'rice',
    'aata': 'flour', 'atta': 'flour', 'maida': 'refined flour',
    'cheeni': 'sugar', 'shakkar': 'sugar',
    'namak': 'salt', 'noon': 'salt',
    'dal': 'lentil', 'daal': 'lentil',
    # Oil
    'tel': 'oil', 'tail': 'oil',
    # Bread
    'roti': 'bread', 'pav': 'bread', 'paav': 'bread',
    # Beverages
    'chai': 'tea', 'chaay': 'tea', 'chay': 'tea',
    'koffe': 'coffee', 'koffee': 'coffee', 'kafi': 'coffee',
    'pani': 'water', 'paani': 'water',
    # Spices
    'mirch': 'chilli', 'mirchi': 'chilli', 'laal mirch': 'red chilli',
    'haldi': 'turmeric', 'haldy': 'turmeric', 'haldee': 'turmeric',
    'dhaniya': 'coriander', 'dhaniye': 'coriander',
    'jeera': 'cumin', 'zeera': 'cumin',
    'elaichi': 'cardamom', 'ilaychi': 'cardamom',
    'laung': 'clove', 'dalchini': 'cinnamon',
    # Vegetables
    'aloo': 'potato', 'aaloo': 'potato',
    'pyaz': 'onion', 'pyaaz': 'onion', 'pyaj': 'onion',
    'tamatar': 'tomato', 'tamaatar': 'tomato',
    'adrak': 'ginger', 'lehsun': 'garlic', 'lahsun': 'garlic',
    'palak': 'spinach', 'gobhi': 'cauliflower', 'gobi': 'cauliflower',
    'matar': 'peas', 'mattar': 'peas',
    # Fruits
    'seb': 'apple', 'kela': 'banana', 'santara': 'orange', 'aam': 'mango',
    'nimbu': 'lemon', 'nimboo': 'lemon',
    # Snacks
    'biscuit': 'biscuits', 'biskut': 'biscuits', 'biskit': 'biscuits',
    'namkeen': 'namkeen', 'namkin': 'namkeen',
    'maggi': 'noodles', 'noodle': 'noodles',
    # Common
    'sabun': 'soap', 'anda': 'egg', 'ande': 'eggs',
}

# Generic/low-value words that should be down-weighted in keyword scoring
GENERIC_WORDS = {'packet', 'pack', 'box', 'bottle', 'bag', 'piece', 'kg', 'gm', 'ml', 'ltr',
                 'powder', 'masala', 'mix', 'small', 'big', 'large', 'medium', 'premium'}

# Intent / concept → product keyword mapping
# Bridges the gap when LLM searches by problem/need rather than product name
INTENT_ALIASES = {
    # Stain & cleaning
    'stain remover': ['surf excel', 'vanish', 'detergent', 'liquid detergent'],
    'stain': ['surf excel', 'vanish', 'detergent'],
    'cleaning': ['vim', 'harpic', 'colin', 'surf excel', 'detergent'],
    'daag': ['surf excel', 'vanish', 'detergent'],      # Hindi: stain
    'saaf': ['surf excel', 'vim', 'detergent'],          # Hindi: clean
    # Breakfast
    'breakfast': ['bread', 'butter', 'jam', 'cornflakes', 'oats', 'milk', 'eggs'],
    'nashta': ['bread', 'butter', 'biscuits', 'cornflakes', 'milk'],  # Hindi: breakfast
    # Tea / chai
    'chai ingredients': ['tea', 'sugar', 'milk', 'elaichi'],
    'chai banane': ['tea', 'sugar', 'milk'],
    # Common cooking needs
    'tadka': ['ghee', 'oil', 'jeera', 'mustard seeds', 'onion', 'garlic'],
    'roti ingredients': ['atta', 'salt', 'oil'],
    'dal ingredients': ['dal', 'salt', 'oil', 'onion', 'tomato', 'garlic'],
    # Pav Bhaji (example from vision)
    'pav bhaji': ['pav', 'pav bhaji masala', 'butter', 'potato', 'onion', 'tomato'],
    # Health
    'cold flu': ['turmeric', 'ginger', 'honey', 'lemon'],
    'fever': ['paracetamol', 'ginger', 'turmeric', 'lemon'],
}


def resolve_aliases(query: str) -> List[str]:
    """Expand a query with multilingual and intent-based aliases. Returns list of candidate search strings."""
    names = [query.lower()]
    q_lower = query.lower().strip()
    
    # Full phrase alias (product name)
    if q_lower in PRODUCT_ALIASES:
        names.append(PRODUCT_ALIASES[q_lower])
    
    # Per-word alias (product name)
    for word in q_lower.split():
        if word in PRODUCT_ALIASES:
            names.append(PRODUCT_ALIASES[word])
    
    # Intent / concept alias — expands to list of product keywords
    if q_lower in INTENT_ALIASES:
        names.extend(INTENT_ALIASES[q_lower])
    
    # Partial phrase match for intent aliases
    for intent_phrase, product_keywords in INTENT_ALIASES.items():
        if intent_phrase in q_lower or q_lower in intent_phrase:
            names.extend(product_keywords)
            break  # Only match the first intent phrase to avoid over-expansion
    
    return list(set(names))



def keyword_score(query: str, product_name: str, all_product_names: List[str]) -> float:
    """
    BM25-inspired keyword score.
    - Tokenizes query into words
    - Words ≥4 chars: substring match
    - Words 3 chars: prefix-only match (word boundary)
    - IDF weighting: rare words score higher
    """
    q_words = [w for w in query.lower().split() if len(w) >= 3]
    if not q_words:
        return 0.0
    
    prod_lower = product_name.lower()
    prod_words = prod_lower.split()
    total_n = max(len(all_product_names), 1)
    
    score = 0.0
    matched = 0
    
    for qw in q_words:
        # Word boundary matching
        if len(qw) == 3:
            hit = any(pw.startswith(qw) for pw in prod_words)
        else:
            hit = qw in prod_lower
        
        if hit:
            # IDF: how many products contain this word?
            df = sum(1 for pn in all_product_names if qw in pn.lower())
            idf = math.log(total_n / (df + 1) + 1)
            
            # Down-weight generic words
            if qw in GENERIC_WORDS:
                idf *= 0.3
            
            score += idf
            matched += 1
    
    # Coverage bonus
    if q_words:
        coverage = matched / len(q_words)
        score *= (0.5 + 0.5 * coverage)
    
    return score


def fuzzy_score(query: str, product_name: str) -> float:
    """SequenceMatcher fuzzy score between query and product name."""
    return SequenceMatcher(None, query.lower(), product_name.lower()).ratio()


class HybridSearchService:
    """
    Hybrid search combining:
    1. Keyword scoring (BM25-like with IDF)
    2. Vector similarity (Titan embeddings cosine)
    3. Fuzzy matching (SequenceMatcher fallback)
    """
    
    def __init__(self):
        self._embed_service = None
    
    @property
    def embed_service(self):
        if self._embed_service is None:
            self._embed_service = get_embedding_service()
        return self._embed_service
    
    def search(
        self,
        query: str,
        products: List[Dict],
        limit: int = 10,
        keyword_weight: float = 0.5,
        vector_weight: float = 0.4,
        fuzzy_weight: float = 0.1,
        min_score: float = 0.15
    ) -> List[Tuple[float, Dict]]:
        """
        Hybrid search across a list of products.
        
        Args:
            query: User search query (e.g., "mirchi powder")
            products: List of product dicts (must have 'name', optionally 'name_vector')
            limit: Max results to return
            keyword_weight: Weight for BM25-like keyword score
            vector_weight: Weight for vector cosine similarity
            fuzzy_weight: Weight for fuzzy string matching
            min_score: Minimum combined score to include in results
            
        Returns:
            List of (score, product) tuples, sorted by score descending
        """
        if not products or not query.strip():
            return []
        
        # Expand query with aliases
        all_queries = resolve_aliases(query)
        
        # Get all product names for IDF calculation
        all_product_names = [p.get('name', '') for p in products]
        
        # Generate query embedding (if vector search available)
        query_embedding = None
        has_vectors = any(p.get('name_vector') for p in products)
        
        if has_vectors:
            # Build expanded query text for embedding (include aliases)
            embed_text = ' '.join(all_queries)
            try:
                query_embedding = self.embed_service.generate_embedding(embed_text)
            except Exception as e:
                logger.warning(f"Query embedding failed, falling back to keyword-only: {e}")
        
        # Score each product
        scored = []
        
        for product in products:
            prod_name = product.get('name', '')
            if not prod_name:
                continue
            
            # 1. Keyword score (best across all query aliases)
            kw_score = max(
                keyword_score(q, prod_name, all_product_names)
                for q in all_queries
            )
            
            # 2. Vector similarity score
            vec_score = 0.0
            if query_embedding and product.get('name_vector'):
                vec_score = self.embed_service.cosine_similarity(
                    query_embedding, product['name_vector']
                )
                # Clamp to [0, 1]
                vec_score = max(0.0, min(1.0, vec_score))
            
            # 3. Fuzzy score (best across all query aliases)
            fz_score = max(
                fuzzy_score(q, prod_name)
                for q in all_queries
            )
            
            # Combined weighted score
            # Normalize keyword score to ~0-1 range (cap at 3.0 = IDF of very rare word)
            kw_normalized = min(kw_score / 3.0, 1.0) if kw_score > 0 else 0.0
            
            # Adjust weights if no vectors available
            if not query_embedding or not product.get('name_vector'):
                # No vector search — redistribute weight
                actual_kw_weight = keyword_weight + vector_weight * 0.7
                actual_fz_weight = fuzzy_weight + vector_weight * 0.3
                actual_vec_weight = 0.0
            else:
                actual_kw_weight = keyword_weight
                actual_vec_weight = vector_weight
                actual_fz_weight = fuzzy_weight
            
            combined = (
                kw_normalized * actual_kw_weight +
                vec_score * actual_vec_weight +
                fz_score * actual_fz_weight
            )
            
            if combined >= min_score:
                scored.append((combined, product))
        
        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        
        if scored:
            top_results = [(round(s, 3), p.get('name')) for s, p in scored[:5]]
            logger.info(f"🔍 Hybrid search '{query}' → {top_results}")
        
        return scored[:limit]


# Singleton
_search_service: Optional[HybridSearchService] = None

def get_search_service() -> HybridSearchService:
    global _search_service
    if _search_service is None:
        _search_service = HybridSearchService()
    return _search_service
