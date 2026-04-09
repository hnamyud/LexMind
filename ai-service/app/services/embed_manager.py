"""
services/embed_manager.py
─────────────────────────
Tải và khởi tạo SentenceTransformer embedding model.

Hàm public:
  load_embed_model(service) → None  (Option B: gán trực tiếp lên service._embed_model)

Chạy trong thread executor (blocking I/O) — gọi từ asyncio.loop.run_in_executor().
"""

import logging

from sentence_transformers import SentenceTransformer


def load_embed_model(service) -> None:
    """
    Tải SentenceTransformer embedding model và gán vào service._embed_model.

    Args:
        service: RAGService instance có attribute _embed_model_id
    """
    try:
        logging.info(f"⏳ Đang tải embedding model {service._embed_model_id}...")
        service._embed_model = SentenceTransformer(service._embed_model_id)
        logging.info(
            f"✅ Embedding model sẵn sàng! "
            f"Số chiều: {service._embed_model.get_sentence_embedding_dimension()}"
        )
    except Exception as e:
        logging.error(f"❌ Lỗi tải embedding model: {e}")
        service._embed_model = None
