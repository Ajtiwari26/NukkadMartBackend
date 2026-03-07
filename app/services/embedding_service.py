"""
Embedding Service using Amazon Titan Text Embeddings V2
Generates vector embeddings for product names for semantic search.
Cost: ~$0.00002 per 1K input tokens (essentially free for product catalogs)
"""
import os
import json
import logging
import numpy as np
from typing import List, Optional
import boto3

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Generate text embeddings via Amazon Titan Text Embeddings V2"""
    
    def __init__(self):
        self.bedrock = boto3.client(
            'bedrock-runtime',
            region_name=os.getenv('AWS_REGION', 'ap-south-1')
        )
        self.model_id = os.getenv('TITAN_EMBED_MODEL_ID', 'amazon.titan-embed-text-v2:0')
        self.dimensions = int(os.getenv('TITAN_EMBED_DIMENSIONS', '256'))
        self._initialized = True
        logger.info(f"EmbeddingService initialized: model={self.model_id}, dims={self.dimensions}")
    
    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        Generate a single embedding vector for the given text.
        Returns a list of floats (256-dim by default) or None on error.
        """
        if not text or not text.strip():
            return None
        
        try:
            body = json.dumps({
                "inputText": text.strip(),
                "dimensions": self.dimensions,
                "normalize": True  # Unit vector for cosine similarity
            })
            
            response = self.bedrock.invoke_model(
                modelId=self.model_id,
                contentType="application/json",
                accept="application/json",
                body=body
            )
            
            result = json.loads(response['body'].read())
            embedding = result.get('embedding', [])
            
            if embedding:
                return embedding
            else:
                logger.warning(f"Empty embedding for text: '{text[:50]}'")
                return None
                
        except Exception as e:
            logger.error(f"Embedding generation failed for '{text[:50]}': {e}")
            return None
    
    def generate_batch_embeddings(self, texts: List[str]) -> List[Optional[List[float]]]:
        """
        Generate embeddings for a batch of texts.
        Titan doesn't support native batching, so we loop (still fast for <1000 items).
        """
        results = []
        for i, text in enumerate(texts):
            embedding = self.generate_embedding(text)
            results.append(embedding)
            if (i + 1) % 50 == 0:
                logger.info(f"  Embedded {i+1}/{len(texts)} products...")
        return results
    
    @staticmethod
    def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """Compute cosine similarity between two vectors. Returns 0.0-1.0."""
        a = np.array(vec_a)
        b = np.array(vec_b)
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))
    
    @staticmethod
    def batch_cosine_similarity(query_vec: List[float], product_vecs: List[List[float]]) -> List[float]:
        """
        Compute cosine similarity between a query vector and multiple product vectors.
        Uses numpy for fast vectorized computation.
        """
        if not product_vecs:
            return []
        
        q = np.array(query_vec)
        P = np.array(product_vecs)
        
        # Normalize
        q_norm = q / (np.linalg.norm(q) + 1e-10)
        P_norms = np.linalg.norm(P, axis=1, keepdims=True) + 1e-10
        P_normalized = P / P_norms
        
        # Dot product = cosine similarity (since both normalized)
        similarities = P_normalized @ q_norm
        return similarities.tolist()


# Singleton
_embedding_service: Optional[EmbeddingService] = None

def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
