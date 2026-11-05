# preproc/pipeline/local_embedder.py
from __future__ import annotations

import logging
from typing import List, Sequence, Optional

from sentence_transformers import SentenceTransformer

from app.preproc.pipeline.interfaces import Embedder

logger = logging.getLogger(__name__)

class LocalEmbedder(Embedder):
    def __init__(
        self,
        model_path: str,
        *,
        device: str = "cpu",
        batch_size: int = 32,
        normalize: bool = True,
        cache_folder: Optional[str] = None,
        target_dim: Optional[int] = None,
    ) -> None:
        """
        model_path:
          - Đường dẫn TUYỆT ĐỐI tới folder model offline (BẮT BUỘC).
          - Ví dụ: /models/vietnamese-sbert
        """
        # Strict Offline Check
        import os
        import numpy as np # Import numpy for padding
        if not os.path.exists(model_path) or not os.path.isdir(model_path):
            raise RuntimeError(
                f"[Strict Offline] Model path not found or not a directory: '{model_path}'. "
                "Did you mount the volume and set EMBED_MODEL_PATH correctly?"
            )

        logger.info("[Strict Offline] Loading embedding model from local: %s (device=%s)", model_path, device)
        
        # local_files_only=True ensures no HTTP call to HuggingFace
        self.model = SentenceTransformer(model_path, device=device, local_files_only=True)
        self.batch_size = int(batch_size)
        self.normalize = bool(normalize)
        self.dim = int(self.model.get_sentence_embedding_dimension())
        self.target_dim = int(target_dim) if target_dim else None
        
        if self.target_dim and self.target_dim > self.dim:
             logger.warning(f"PADDING ENABLED: Model dim {self.dim} -> Target dim {self.target_dim}")
        
        logger.info("Embedding model loaded successfully. dim=%s (target=%s)", self.dim, self.target_dim)

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []
        embs = self.model.encode(
            list(texts),
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=self.normalize,
        )
        # Pilot Hotfix: Padding
        if self.target_dim and self.target_dim > self.dim:
            # Pad with zeros
            import numpy as np
            pad_width = ((0, 0), (0, self.target_dim - self.dim))
            embs = np.pad(embs, pad_width, mode='constant', constant_values=0)
            
        return embs.tolist()
