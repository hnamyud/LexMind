"""
services/embed_manager.py
-------------------------
Load embedding model bang ONNX Runtime.

Public:
  load_embed_model(service) -> None

Ham nay duoc goi trong thread executor vi viec download/cache model va khoi tao
ONNX session la blocking I/O.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable

import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download, snapshot_download
from transformers import AutoTokenizer


DEFAULT_ONNX_MODEL_FILE = "onnx/model.onnx"
DEFAULT_HF_TOKENIZER_ALLOW_PATTERNS = [
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "added_tokens.json",
    "vocab.txt",
    "bpe.codes",
    "sentence_bert_config.json",
    "1_Pooling/config.json",
]


class OnnxEmbeddingModel:
    """SentenceTransformer-compatible wrapper chi cho cac API dang duoc dung."""

    def __init__(
        self,
        model_id: str,
        *,
        model_file: str = DEFAULT_ONNX_MODEL_FILE,
        providers: list[str] | None = None,
        batch_size: int = 32,
        max_length: int | None = None,
        normalize_embeddings: bool = False,
    ) -> None:
        self.model_id = model_id
        self.model_file = model_file
        self.batch_size = batch_size
        self.normalize_embeddings = normalize_embeddings

        self.model_dir = Path(
            snapshot_download(
                repo_id=model_id,
                allow_patterns=DEFAULT_HF_TOKENIZER_ALLOW_PATTERNS,
            )
        )
        self.onnx_path = self._download_onnx_model()
        if not self.onnx_path.exists():
            raise FileNotFoundError(f"Khong tim thay ONNX model: {self.onnx_path}")

        self.tokenizer = AutoTokenizer.from_pretrained(str(self.model_dir), use_fast=True)
        self.max_length = max_length or self._read_max_length() or 256

        session_options = ort.SessionOptions()
        session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            str(self.onnx_path),
            sess_options=session_options,
            providers=self._resolve_providers(providers),
        )
        self.input_names = {input_meta.name for input_meta in self.session.get_inputs()}
        self._embedding_dimension = self._read_embedding_dimension()

    def encode(self, sentences: str | list[str], **kwargs) -> np.ndarray:
        """Encode text thanh numpy array, tuong thich voi `.tolist()` hien co."""
        single_input = isinstance(sentences, str)
        items = [sentences] if single_input else list(sentences)
        if not items:
            return np.empty((0, self.get_sentence_embedding_dimension()), dtype=np.float32)

        batch_size = int(kwargs.get("batch_size") or self.batch_size)
        normalize = bool(kwargs.get("normalize_embeddings", self.normalize_embeddings))
        embeddings: list[np.ndarray] = []

        for start in range(0, len(items), batch_size):
            batch = items[start : start + batch_size]
            encoded = self.tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="np",
            )
            attention_mask = encoded["attention_mask"].astype(np.int64)
            ort_inputs = self._build_onnx_inputs(encoded)
            outputs = self.session.run(None, ort_inputs)
            token_embeddings = outputs[0]
            sentence_embeddings = (
                token_embeddings
                if token_embeddings.ndim == 2
                else self._mean_pool(token_embeddings, attention_mask)
            )
            if normalize:
                sentence_embeddings = self._normalize(sentence_embeddings)
            embeddings.append(sentence_embeddings.astype(np.float32))

        result = np.vstack(embeddings)
        return result[0] if single_input else result

    def get_sentence_embedding_dimension(self) -> int:
        return self._embedding_dimension

    def _build_onnx_inputs(self, encoded) -> dict[str, np.ndarray]:
        ort_inputs: dict[str, np.ndarray] = {}
        for name in self.input_names:
            if name in encoded:
                ort_inputs[name] = encoded[name].astype(np.int64)
            elif name == "token_type_ids" and "input_ids" in encoded:
                ort_inputs[name] = np.zeros_like(encoded["input_ids"], dtype=np.int64)
        missing = self.input_names - set(ort_inputs)
        if missing:
            raise ValueError(f"Tokenizer khong tao du input cho ONNX model: {sorted(missing)}")
        return ort_inputs

    @staticmethod
    def _mean_pool(token_embeddings: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
        mask = np.expand_dims(attention_mask, axis=-1).astype(np.float32)
        summed = np.sum(token_embeddings * mask, axis=1)
        counts = np.clip(mask.sum(axis=1), a_min=1e-9, a_max=None)
        return summed / counts

    @staticmethod
    def _normalize(embeddings: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        return embeddings / np.clip(norms, a_min=1e-12, a_max=None)

    @staticmethod
    def _resolve_providers(providers: Iterable[str] | None) -> list[str]:
        available = set(ort.get_available_providers())
        requested = list(providers or ["CPUExecutionProvider"])
        resolved = [provider for provider in requested if provider in available]
        if not resolved:
            logging.warning(
                "Khong provider ONNX nao trong %s kha dung; dung CPUExecutionProvider.",
                requested,
            )
            return ["CPUExecutionProvider"]
        return resolved

    def _read_max_length(self) -> int | None:
        config_path = self.model_dir / "sentence_bert_config.json"
        config = self._read_json(config_path)
        value = config.get("max_seq_length")
        return int(value) if value else None

    def _read_embedding_dimension(self) -> int:
        pooling_config = self._read_json(self.model_dir / "1_Pooling" / "config.json")
        value = pooling_config.get("word_embedding_dimension")
        if value:
            return int(value)

        output_shape = self.session.get_outputs()[0].shape
        if output_shape and isinstance(output_shape[-1], int):
            return int(output_shape[-1])
        raise ValueError("Khong xac dinh duoc so chieu embedding tu ONNX model.")

    def _download_onnx_model(self) -> Path:
        local_snapshot_path = self.model_dir / self.model_file
        if local_snapshot_path.exists():
            return local_snapshot_path

        logging.info("Dang tai file ONNX truc tiep tu Hugging Face: %s", self.model_file)
        return Path(
            hf_hub_download(
                repo_id=self.model_id,
                filename=self.model_file,
            )
        )

    @staticmethod
    def _read_json(path: Path) -> dict:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)


def load_embed_model(service) -> None:
    """
    Tai ONNX embedding model va gan vao service._embed_model.

    Args:
        service: RAGService instance co attribute _embed_model_id
    """
    try:
        providers = [
            provider.strip()
            for provider in getattr(service, "_embed_onnx_providers", "").split(",")
            if provider.strip()
        ]
        logging.info(
            "Dang tai embedding model bang ONNX: %s (%s)",
            service._embed_model_id,
            DEFAULT_ONNX_MODEL_FILE,
        )
        service._embed_model = OnnxEmbeddingModel(
            service._embed_model_id,
            providers=providers or None,
            batch_size=getattr(service, "_embed_batch_size", 32),
            max_length=getattr(service, "_embed_max_length", None),
            normalize_embeddings=getattr(service, "_embed_normalize", False),
        )
        logging.info(
            "Embedding ONNX san sang. So chieu: %s",
            service._embed_model.get_sentence_embedding_dimension(),
        )
    except Exception as exc:
        logging.exception("Loi tai embedding model ONNX: %s", exc)
        service._embed_model = None
