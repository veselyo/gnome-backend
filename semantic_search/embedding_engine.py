"""
Local embedding engine using BAAI/bge-large-en-v1.5.
100% private - no cloud APIs, no data leaves your Mac.
"""
from sentence_transformers import SentenceTransformer
from typing import List, Union
from pathlib import Path
import os
import logging
from PIL import Image

logger = logging.getLogger(__name__)

# Singleton model instance for performance
_MODEL = None
_MODEL_PATH = None


def init_local_embedder():
    """
    Initialize local BGE embedding model (BAAI/bge-large-en-v1.5).
    Returns the model instance for embedding generation.
    
    This runs 100% locally - no API keys, no internet after initial setup.
    Optimized for Apple Silicon (MPS) and Intel (CPU).
    """
    global _MODEL, _MODEL_PATH
    
    if _MODEL is not None:
        return _MODEL
    
    try:
        # Determine model path (bundled in app or development)
        if getattr(__import__('sys'), 'frozen', False):
            # Production: Model bundled with app
            app_path = Path(__import__('sys').executable).parent
            _MODEL_PATH = app_path / 'resources' / 'bge-onnx'
        else:
            # Development: Model in project resources
            _MODEL_PATH = Path(__file__).resolve().parent.parent / 'resources' / 'bge-onnx'
        
        logger.info(f"Loading local BGE model from: {_MODEL_PATH}")
        
        # Load model with optimal device
        import torch
        if torch.backends.mps.is_available():
            device = 'mps'  # Apple Silicon GPU
            logger.info("🚀 Using Apple Silicon GPU (MPS) for fast inference")
        elif torch.cuda.is_available():
            device = 'cuda'  # NVIDIA GPU (unlikely on Mac)
            logger.info("🚀 Using CUDA GPU for inference")
        else:
            device = 'cpu'  # Intel CPU
            logger.info("💻 Using CPU for inference")
        
        _MODEL = SentenceTransformer(str(_MODEL_PATH), device=device)
        
        logger.info("✅ Local embedding model loaded successfully")
        logger.info(f"   Model: BAAI/bge-large-en-v1.5")
        logger.info(f"   Dimensions: 1024")
        logger.info(f"   Device: {device}")
        logger.info(f"   Privacy: 100% LOCAL - No cloud APIs!")
        
        return _MODEL
        
    except Exception as e:
        logger.error(f"❌ Failed to load local model: {e}")
        logger.error("Make sure the model is downloaded to resources/bge-onnx/")
        raise


def embed_text(texts: Union[str, List[str]], normalize: bool = True) -> List[List[float]]:
    """
    Generate embeddings for text using local BGE model.
    
    Args:
        texts: Single text string or list of text strings
        normalize: Whether to L2-normalize embeddings (default True)
    
    Returns:
        List of 1024-dimensional embedding vectors
    """
    model = init_local_embedder()
    
    # Convert single string to list
    if isinstance(texts, str):
        texts = [texts]
    
    try:
        embeddings = model.encode(
            texts,
            normalize_embeddings=normalize,
            show_progress_bar=len(texts) > 10  # Show progress for large batches
        )
        
        return embeddings.tolist()
        
    except Exception as e:
        logger.error(f"Failed to generate embeddings: {e}")
        raise


def embed_images(images: List[Image.Image], normalize: bool = True) -> List[List[float]]:
    """
    Generate embeddings for images using local BGE model.
    For images, we extract text via OCR first (better for documents).
    
    Args:
        images: List of PIL Image objects
        normalize: Whether to L2-normalize embeddings
    
    Returns:
        List of 1024-dimensional embedding vectors
    """
    try:
        # Try OCR first (better for document images)
        import pytesseract
        
        texts = []
        for img in images:
            try:
                text = pytesseract.image_to_string(img)
                if text.strip():
                    texts.append(text)
                else:
                    # Fallback: Use image description
                    texts.append(f"Image content: {img.size[0]}x{img.size[1]} pixels")
            except Exception as ocr_error:
                logger.warning(f"OCR failed, using image description: {ocr_error}")
                texts.append(f"Image content: {img.size[0]}x{img.size[1]} pixels")
        
        # Embed the extracted text
        return embed_text(texts, normalize=normalize)
        
    except ImportError:
        logger.warning("Tesseract not available, using image descriptions")
        # Fallback: Simple image descriptions
        texts = [f"Image: {img.size[0]}x{img.size[1]}" for img in images]
        return embed_text(texts, normalize=normalize)


def embed_pdf(images: List[Image.Image]) -> List[float]:
    """
    Legacy function for compatibility with existing code.
    Embeds PDF pages (as images) into a single vector.
    
    Args:
        images: List of PDF page images
    
    Returns:
        Single 1024-dimensional embedding (averaged across pages)
    """
    if not images:
        raise ValueError("No images provided for embedding")
    
    # Embed all pages
    page_embeddings = embed_images(images, normalize=True)
    
    # Average embeddings across pages for document-level representation
    import numpy as np
    avg_embedding = np.mean(page_embeddings, axis=0)
    
    # Re-normalize after averaging
    norm = np.linalg.norm(avg_embedding)
    if norm > 0:
        avg_embedding = avg_embedding / norm
    
    return avg_embedding.tolist()


# Legacy compatibility functions (for existing code)
def init_voyage():
    """Legacy function - now uses local model instead of Voyage AI."""
    logger.warning("init_voyage() called - using local embedder instead")
    return init_local_embedder()


class LocalEmbedderClient:
    """
    Drop-in replacement for Voyage AI client.
    Provides same interface but uses local BGE model.
    """
    
    def __init__(self):
        self.model = init_local_embedder()
    
    def embed(self, texts: List[str], model: str = "bge-large", input_type: str = "document"):
        """
        Generate embeddings (compatible with Voyage AI interface).
        
        Args:
            texts: List of text strings
            model: Ignored (always uses BGE)
            input_type: Ignored (BGE handles both query and document)
        
        Returns:
            Object with .embeddings attribute
        """
        embeddings = embed_text(texts, normalize=True)
        
        # Return object with same interface as Voyage
        class EmbeddingResponse:
            def __init__(self, emb):
                self.embeddings = emb
        
        return EmbeddingResponse(embeddings)
    
    def multimodal_embed(self, inputs, model: str = "bge-large", input_type: str = "document"):
        """
        Multimodal embedding (text + images).
        For images, we extract text via OCR first.
        """
        results = []
        
        for input_item in inputs:
            if isinstance(input_item, list):
                # List of images
                emb = embed_images(input_item, normalize=True)
                results.append(emb[0] if len(emb) == 1 else emb)
            else:
                # Single image
                emb = embed_images([input_item], normalize=True)
                results.append(emb[0])
        
        class EmbeddingResponse:
            def __init__(self, emb):
                self.embeddings = emb
        
        return EmbeddingResponse(results)
