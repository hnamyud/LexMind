"""
app/cache/semantic_cache.py
────────────────────────────
Semantic Cache cho RAG pipeline pháp lý sử dụng RedisVL.

Chiến lược:
  - Cache check diễn ra SAU node router_rewrite (đã có route, entities, legal_query)
  - Chỉ cache các câu hỏi route = "use_tool" (legal questions)
  - Dùng HNSW vector index cho semantic search (O(log n), scalable)
  - Hỗ trợ filter theo vehicle_type, violation_type để tăng precision
  - Graceful fallback: nếu Redis down, pipeline vẫn chạy bình thường

Eviction Policy — LFU with Time Decay:
  - score = (1 + hit_count) × e^(-λ × age_hours)
  - λ = DECAY_RATE (default 0.05, half-life ≈ 14h)
  - Entries có score thấp nhất bị evict khi vượt MAX_ENTRIES
  - Background cleanup mỗi CLEANUP_INTERVAL_SECONDS loại entries score < MIN_SCORE

Schema Redis (Hash storage):
  - vehicle_type   : TAG  — loại xe (xe_may, o_to, ...)
  - violation_type  : TAG  — loại vi phạm (vuot_den_do, nong_do_con, ...)
  - law_tags        : TAG  — tag luật (nd_168_2024, ...) dùng cho invalidation
  - user_query      : TEXT — câu hỏi gốc (debug/inspect)
  - created_at      : NUMERIC — timestamp tạo
  - hit_count       : NUMERIC — số lần cache hit
  - query_vector    : VECTOR(HNSW, dim=768, cosine) — semantic search
  - response        : Stored field — câu trả lời cached
  - metadata_json   : Stored field — metadata bổ sung (JSON string)
"""

import asyncio
import functools
import json
import logging
import math
import time
from typing import Any, Optional

import numpy as np
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redisvl.index import SearchIndex
from redisvl.query import VectorQuery
from redisvl.query.filter import Tag
from redisvl.schema import IndexSchema


# ---------------------------------------------------------------------------
# Index Schema — custom cho legal domain
# ---------------------------------------------------------------------------

_SCHEMA_DICT = {
    "index": {
        "name": "legal_cache",
        "prefix": "cache:",
        "storage_type": "hash",
    },
    "fields": [
        # ── Filter dimensions (TAG) ──────────────────────────
        {"name": "vehicle_type", "type": "tag"},
        {"name": "violation_type", "type": "tag"},
        {"name": "law_tags", "type": "tag"},

        # ── Searchable text (TEXT) ───────────────────────────
        {"name": "user_query", "type": "text"},

        # ── Numeric để sort/filter theo thời gian ───────────
        {"name": "created_at", "type": "numeric"},
        {"name": "hit_count", "type": "numeric"},

        # ── Vector semantic ──────────────────────────────────
        {
            "name": "query_vector",
            "type": "vector",
            "attrs": {
                "dims": 768,
                "distance_metric": "cosine",
                "algorithm": "hnsw",
                "m": 32,
                "ef_construction": 400,
            },
        },
    ],
}


class SemanticCacheService:
    """
    Semantic Cache cho RAG pipeline pháp lý.

    Sử dụng RedisVL SearchIndex + VectorQuery để:
      1. Check: tìm cache entry tương tự ngữ nghĩa với câu hỏi hiện tại
      2. Store: lưu câu hỏi + response vào cache
      3. Invalidate: xóa cache theo tag hoặc flush toàn bộ

    Parameters
    ----------
    redis_url : str
        Redis connection URL (cần Redis Stack cho RediSearch).
    embed_model : object
        Model embedding đã load sẵn, có encode() và dùng chung với graph_retrieval.
    ttl : int | None
        Time-to-live cho cache entries (giây). None = không hết hạn.
    """

    # ── Threshold ─────────────────────────────────────────────────────
    # Cosine distance = 1 - similarity.
    # DISTANCE_THRESHOLD = 0.05  →  similarity ≥ 0.95
    DISTANCE_THRESHOLD = 0.05

    # ── LFU + Time Decay ─────────────────────────────────────────────
    # score = (1 + hit_count) × e^(-DECAY_RATE × age_hours)
    # DECAY_RATE  = 0.05   → half-life ≈ 14h (ln2/0.05 ≈ 13.86h)
    # Ý nghĩa:
    #   - Entry mới (0 hits, 0h):  score = 1.0
    #   - Entry mới (0 hits, 14h): score ≈ 0.5  → vẫn sống
    #   - Entry cũ  (0 hits, 48h): score ≈ 0.09 → bị evict
    #   - Entry hot (10 hits, 48h): score ≈ 1.0  → vẫn sống
    DECAY_RATE = 0.05
    MAX_ENTRIES = 10_000              # ngưỡng kích hoạt eviction
    EVICT_BATCH_PERCENT = 0.10        # evict 10% entries score thấp nhất
    MIN_SCORE_THRESHOLD = 0.1         # cleanup entries score < 0.1
    CLEANUP_INTERVAL_SECONDS = 3600   # chạy cleanup mỗi 1h

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        embed_model: Any = None,
        ttl: Optional[int] = 86400,
    ):
        self._redis_url = redis_url
        self._embed_model = embed_model
        self._ttl = ttl

        # Stats tracking
        self._hits = 0
        self._misses = 0
        self._evictions = 0

        # Redis + Index
        self._redis_client: Optional[Redis] = None
        self._index: Optional[SearchIndex] = None
        self._connected = False

        # Background cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None

    async def _run_blocking(self, func, *args, **kwargs):
        """Run sync RedisVL/Redis work outside the event loop."""
        loop = asyncio.get_running_loop()
        call = functools.partial(func, *args, **kwargs)
        return await loop.run_in_executor(None, call)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Kết nối Redis và tạo/kiểm tra index."""
        try:
            await self._run_blocking(self._initialize_sync)

            # Khởi động background cleanup task
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

            logging.info(
                f"✅ Redis Semantic Cache kết nối thành công! "
                f"(threshold={self.DISTANCE_THRESHOLD}, decay_rate={self.DECAY_RATE}, "
                f"max_entries={self.MAX_ENTRIES}, cleanup_interval={self.CLEANUP_INTERVAL_SECONDS}s)"
            )
        except (RedisConnectionError, OSError, Exception) as e:
            logging.warning(
                f"⚠️ Không thể kết nối Redis Semantic Cache: {e}. "
                f"Pipeline sẽ chạy không có cache."
            )
            self._connected = False

    def _initialize_sync(self) -> None:
        self._redis_client = Redis.from_url(
            self._redis_url,
            decode_responses=False,  # RedisVL cần bytes cho vector
        )
        self._redis_client.ping()

        schema = IndexSchema.from_dict(_SCHEMA_DICT)
        self._index = SearchIndex(schema=schema, redis_client=self._redis_client)

        try:
            self._index.create(overwrite=False)
            logging.info("✅ Redis Semantic Cache index 'legal_cache' đã sẵn sàng.")
        except ResponseError as e:
            if "Index already exists" in str(e):
                logging.info("✅ Redis Semantic Cache index 'legal_cache' đã tồn tại, dùng lại.")
            else:
                raise

        self._connected = True

    async def close(self) -> None:
        """Đóng kết nối Redis và hủy background tasks."""
        # Cancel cleanup task
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        if self._redis_client:
            try:
                await self._run_blocking(self._redis_client.close)
                logging.info("✅ Đã đóng kết nối Redis Semantic Cache.")
            except Exception as e:
                logging.warning(f"⚠️ Lỗi khi đóng Redis: {e}")

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Embed helper
    # ------------------------------------------------------------------

    def _embed(self, text: str) -> list[float]:
        """Tạo embedding vector từ text."""
        return self._embed_model.encode(text).tolist()

    # ------------------------------------------------------------------
    # Cache Check
    # ------------------------------------------------------------------

    async def check(
        self,
        query: str,
        vehicle_type: str = "",
        violation_type: str = "",
    ) -> Optional[dict]:
        """
        Tìm cache entry tương tự ngữ nghĩa với query.

        Parameters
        ----------
        query : str
            Câu hỏi đã chuẩn hóa (legal_query từ router).
        vehicle_type : str
            Loại xe để filter (optional, tăng precision).
        violation_type : str
            Loại vi phạm để filter (optional).

        Returns
        -------
        dict | None
            Cache hit dict với keys: response, metadata, distance.
            None nếu không tìm thấy hoặc Redis lỗi.
        """
        if not self._connected or not self._index:
            return None

        try:
            return await self._run_blocking(
                self._check_sync,
                query,
                vehicle_type,
                violation_type,
            )
        except Exception as e:
            logging.warning(f"[CACHE] Lỗi khi check cache: {e}")
            self._misses += 1
            return None

    def _check_sync(
        self,
        query: str,
        vehicle_type: str = "",
        violation_type: str = "",
    ) -> Optional[dict]:
        # Tạo vector từ query
        query_vector = self._embed(query)

        # ── Build compound filter expression ─────────────────
        has_vehicle = bool(vehicle_type)
        has_violation = bool(violation_type)
        filter_expr = None
        if has_vehicle:
            vehicle_filter = Tag("vehicle_type") == self._normalize_tag(vehicle_type)
            filter_expr = vehicle_filter
        if has_violation:
            violation_filter = Tag("violation_type") == self._normalize_tag(violation_type)
            filter_expr = (filter_expr & violation_filter) if filter_expr else violation_filter

        # Vector query
        vq = VectorQuery(
            vector=query_vector,
            vector_field_name="query_vector",
            return_fields=[
                "user_query", "response", "metadata_json",
                "vehicle_type", "violation_type", "hit_count",
                "created_at",
            ],
            num_results=1,
            filter_expression=filter_expr,
        )

        results = self._index.query(vq)

        if not results:
            self._misses += 1
            logging.info(f"[CACHE] MISS — không tìm thấy kết quả cho: '{query[:60]}'")
            return None

        # Kiểm tra distance (strict: 0.05 = similarity ≥ 0.95)
        top_result = results[0]
        distance = float(top_result.get("vector_distance", 999))

        if distance > self.DISTANCE_THRESHOLD:
            self._misses += 1
            logging.info(
                f"[CACHE] MISS — distance={distance:.4f} > threshold={self.DISTANCE_THRESHOLD} "
                f"(similarity={1 - distance:.4f} < 0.95) cho: '{query[:60]}'"
            )
            return None

        # Cache HIT!
        self._hits += 1

        # Decode response (bytes → str)
        response_raw = top_result.get("response", b"")
        response = response_raw.decode("utf-8") if isinstance(response_raw, bytes) else str(response_raw)

        metadata_raw = top_result.get("metadata_json", b"{}")
        metadata_str = metadata_raw.decode("utf-8") if isinstance(metadata_raw, bytes) else str(metadata_raw)
        metadata = json.loads(metadata_str) if metadata_str else {}

        cached_query_raw = top_result.get("user_query", b"")
        cached_query = cached_query_raw.decode("utf-8") if isinstance(cached_query_raw, bytes) else str(cached_query_raw)

        # Cập nhật hit_count
        key = top_result.get("id", "")
        if key:
            try:
                current_hits = int(top_result.get("hit_count", 0) or 0)
                self._redis_client.hset(key, "hit_count", current_hits + 1)
                # Refresh TTL
                if self._ttl:
                    self._redis_client.expire(key, self._ttl)
            except Exception:
                pass  # Non-critical

        logging.info(
            f"[CACHE] HIT ✅ — distance={distance:.4f} (similarity={1 - distance:.4f}), "
            f"cached_query='{cached_query[:60]}', "
            f"current_query='{query[:60]}'"
        )

        return {
            "response": response,
            "metadata": metadata,
            "distance": distance,
            "cached_query": cached_query,
        }

    # ------------------------------------------------------------------
    # Cache Store
    # ------------------------------------------------------------------

    async def store(
        self,
        query: str,
        response: str,
        entities: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ) -> Optional[str]:
        """
        Lưu query + response vào cache.

        Parameters
        ----------
        query : str
            Câu hỏi đã chuẩn hóa (legal_query).
        response : str
            Câu trả lời đầy đủ.
        entities : dict
            Entities từ router (vehicle_type, violation, ...).
        metadata : dict
            Metadata bổ sung (sources, response_style, ...).

        Returns
        -------
        str | None
            Redis key nếu store thành công, None nếu lỗi.
        """
        if not self._connected or not self._index:
            return None

        entities = entities or {}
        metadata = metadata or {}

        try:
            # Evict nếu vượt MAX_ENTRIES trước khi store
            await self._evict_if_needed()
            return await self._run_blocking(
                self._store_sync,
                query,
                response,
                entities,
                metadata,
            )
        except Exception as e:
            logging.warning(f"[CACHE] Lỗi khi store cache: {e}")
            return None

    def _store_sync(
        self,
        query: str,
        response: str,
        entities: dict,
        metadata: dict,
    ) -> Optional[str]:
        # Tạo vector
        query_vector = self._embed(query)

        # Chuẩn bị data
        vehicle_type = self._normalize_tag(entities.get("vehicle_type", "") or "")
        violation_type = self._normalize_tag(entities.get("violation", "") or "")

        data = {
            "user_query": query,
            "response": response,
            "vehicle_type": vehicle_type or "unknown",
            "violation_type": violation_type or "unknown",
            "law_tags": "nd_168_2024",
            "created_at": int(time.time()),
            "hit_count": 0,
            "metadata_json": json.dumps(metadata, ensure_ascii=False),
            "query_vector": np.array(query_vector, dtype=np.float32).tobytes(),
        }

        # Load vào index
        keys = self._index.load([data], id_field=None)

        # Set TTL fallback (safety net, LFU sẽ evict trước TTL trong hầu hết cases)
        if self._ttl and keys:
            for key in keys:
                try:
                    self._redis_client.expire(key, self._ttl)
                except Exception:
                    pass

        logging.info(
            f"[CACHE] STORED — query='{query[:60]}', "
            f"vehicle={vehicle_type}, violation={violation_type}, "
            f"response_len={len(response)}"
        )
        return keys[0] if keys else None

    # ------------------------------------------------------------------
    # LFU + Time Decay — Eviction Logic
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_score(hit_count: int, created_at: int, now: Optional[int] = None) -> float:
        """
        Tính LFU score với exponential time decay.

        score = (1 + hit_count) × e^(-λ × age_hours)

        Parameters
        ----------
        hit_count : int
            Số lần cache entry được hit.
        created_at : int
            Unix timestamp lúc entry được tạo.
        now : int | None
            Timestamp hiện tại (mặc định = time.time()).

        Returns
        -------
        float
            Score ≥ 0. Càng cao = càng "đáng giữ".
        """
        if now is None:
            now = int(time.time())
        age_hours = max(0, (now - created_at)) / 3600.0
        return (1 + hit_count) * math.exp(-SemanticCacheService.DECAY_RATE * age_hours)

    async def _evict_if_needed(self) -> int:
        """
        Kiểm tra số entries hiện tại. Nếu ≥ MAX_ENTRIES, evict batch
        entries có LFU score thấp nhất.

        Returns số entries đã evict.
        """
        if not self._connected or not self._index or not self._redis_client:
            return 0

        try:
            return await self._run_blocking(self._evict_if_needed_sync)
        except Exception as e:
            logging.warning(f"[CACHE] Lỗi kiểm tra eviction: {e}")
            return 0

    def _evict_if_needed_sync(self) -> int:
        info = self._index.info()
        num_docs = int(info.get("num_docs", 0))

        if num_docs < self.MAX_ENTRIES:
            return 0

        return self._evict_lowest_scored_sync(
            count=int(num_docs * self.EVICT_BATCH_PERCENT)
        )

    async def _evict_lowest_scored(self, count: int = 100) -> int:
        """
        Scan tất cả cache entries, tính score, xóa `count` entries
        có score thấp nhất.

        Returns số entries đã xóa.
        """
        if not self._connected or not self._redis_client:
            return 0

        try:
            return await self._run_blocking(self._evict_lowest_scored_sync, count)
        except Exception as e:
            logging.warning(f"[CACHE] Lỗi khi evict: {e}")
            return 0

    def _evict_lowest_scored_sync(self, count: int = 100) -> int:
        now = int(time.time())
        scored_keys: list[tuple[float, str]] = []  # (score, key)

        # Scan all cache keys
        cursor = 0
        while True:
            cursor, keys = self._redis_client.scan(
                cursor=cursor, match="cache:*", count=200
            )
            for key in keys:
                try:
                    fields = self._redis_client.hmget(key, "hit_count", "created_at")
                    hit_count = int(fields[0] or 0) if fields[0] else 0
                    created_at = int(fields[1] or 0) if fields[1] else 0
                    score = self._compute_score(hit_count, created_at, now)
                    key_str = key.decode("utf-8") if isinstance(key, bytes) else str(key)
                    scored_keys.append((score, key_str))
                except Exception:
                    continue
            if cursor == 0:
                break

        if not scored_keys:
            return 0

        # Sort ascending by score, evict lowest
        scored_keys.sort(key=lambda x: x[0])
        to_evict = scored_keys[:count]

        evicted = 0
        for score, key in to_evict:
            try:
                self._redis_client.delete(key)
                evicted += 1
            except Exception:
                continue

        self._evictions += evicted
        logging.info(
            f"[CACHE] LFU EVICT — evicted={evicted}/{count}, "
            f"min_score={to_evict[0][0]:.4f}, max_score={to_evict[-1][0]:.4f}"
        )
        return evicted

    async def cleanup(self) -> int:
        """
        Xóa tất cả entries có LFU score < MIN_SCORE_THRESHOLD.
        Dùng cho periodic maintenance hoặc gọi thủ công.

        Returns số entries đã xóa.
        """
        if not self._connected or not self._redis_client:
            return 0

        try:
            return await self._run_blocking(self._cleanup_sync)
        except Exception as e:
            logging.warning(f"[CACHE] Lỗi khi cleanup: {e}")
            return 0

    def _cleanup_sync(self) -> int:
        now = int(time.time())
        evicted = 0

        cursor = 0
        while True:
            cursor, keys = self._redis_client.scan(
                cursor=cursor, match="cache:*", count=200
            )
            for key in keys:
                try:
                    fields = self._redis_client.hmget(key, "hit_count", "created_at")
                    hit_count = int(fields[0] or 0) if fields[0] else 0
                    created_at = int(fields[1] or 0) if fields[1] else 0
                    score = self._compute_score(hit_count, created_at, now)
                    if score < self.MIN_SCORE_THRESHOLD:
                        self._redis_client.delete(key)
                        evicted += 1
                except Exception:
                    continue
            if cursor == 0:
                break

        self._evictions += evicted
        if evicted > 0:
            logging.info(
                f"[CACHE] CLEANUP — removed {evicted} entries with score < {self.MIN_SCORE_THRESHOLD}"
            )
        return evicted

    async def _periodic_cleanup(self) -> None:
        """
        Background task: chạy cleanup() theo CLEANUP_INTERVAL_SECONDS.
        Tự động cancel khi close() được gọi.
        """
        while True:
            try:
                await asyncio.sleep(self.CLEANUP_INTERVAL_SECONDS)
                if self._connected:
                    removed = await self.cleanup()
                    if removed > 0:
                        logging.info(f"[CACHE] Periodic cleanup: removed {removed} stale entries")
            except asyncio.CancelledError:
                logging.info("[CACHE] Periodic cleanup task cancelled.")
                break
            except Exception as e:
                logging.warning(f"[CACHE] Periodic cleanup error: {e}")

    # ------------------------------------------------------------------
    # Cache Management
    # ------------------------------------------------------------------

    async def clear(self) -> bool:
        """Xóa toàn bộ cache entries (giữ index)."""
        if not self._connected or not self._index:
            return False

        try:
            await self._run_blocking(self._index.clear)
            self._hits = 0
            self._misses = 0
            self._evictions = 0
            logging.info("[CACHE] Đã xóa toàn bộ cache entries.")
            return True
        except Exception as e:
            logging.warning(f"[CACHE] Lỗi khi clear cache: {e}")
            return False

    async def invalidate_by_tag(self, law_tag: str) -> int:
        """
        Xóa cache entries theo law_tag sử dụng RediSearch TAG query.
        Nhanh hơn SCAN vì tận dụng index có sẵn.

        Returns số entries đã xóa.
        """
        if not self._connected or not self._redis_client or not self._index:
            return 0

        try:
            return await self._run_blocking(self._invalidate_by_tag_sync, law_tag)
        except Exception as e:
            logging.warning(f"[CACHE] Lỗi khi invalidate: {e}")
            return 0

    def _invalidate_by_tag_sync(self, law_tag: str) -> int:
        normalized_tag = self._normalize_tag(law_tag)
        # Dùng RediSearch FT.SEARCH với TAG filter thay vì SCAN
        filter_expr = Tag("law_tags") == normalized_tag
        vq = VectorQuery(
            vector=[0.0] * 768,  # dummy vector, chỉ cần filter
            vector_field_name="query_vector",
            return_fields=[],
            num_results=1000,  # batch size
            filter_expression=filter_expr,
        )
        results = self._index.query(vq)

        count = 0
        for result in results:
            key = result.get("id", "")
            if key:
                try:
                    self._redis_client.delete(key)
                    count += 1
                except Exception:
                    continue

        logging.info(f"[CACHE] Invalidated {count} entries với tag '{law_tag}' (RediSearch)")
        return count

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def aget_stats(self) -> dict:
        """Async-safe cache statistics for FastAPI endpoints."""
        return await self._run_blocking(self.get_stats)

    def get_stats(self) -> dict:
        """Trả về cache statistics bao gồm LFU eviction info."""
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0.0

        stats = {
            "connected": self._connected,
            "hits": self._hits,
            "misses": self._misses,
            "total_requests": total,
            "hit_rate_percent": round(hit_rate, 2),
            "evictions": self._evictions,
            "distance_threshold": self.DISTANCE_THRESHOLD,
            "similarity_threshold": 1 - self.DISTANCE_THRESHOLD,
            "ttl_seconds": self._ttl,
            "lfu": {
                "decay_rate": self.DECAY_RATE,
                "half_life_hours": round(math.log(2) / self.DECAY_RATE, 1),
                "max_entries": self.MAX_ENTRIES,
                "evict_batch_percent": self.EVICT_BATCH_PERCENT,
                "min_score_threshold": self.MIN_SCORE_THRESHOLD,
                "cleanup_interval_seconds": self.CLEANUP_INTERVAL_SECONDS,
            },
        }

        # Thêm index info nếu connected
        if self._connected and self._index:
            try:
                info = self._index.info()
                num_docs = int(info.get("num_docs", 0))
                stats["total_entries"] = num_docs
                stats["capacity_percent"] = round(
                    (num_docs / self.MAX_ENTRIES * 100) if self.MAX_ENTRIES > 0 else 0, 1
                )
            except Exception:
                stats["total_entries"] = None
                stats["capacity_percent"] = None

        return stats

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_tag(value: str) -> str:
        """
        Chuẩn hóa giá trị TAG cho Redis:
        - lowercase
        - thay khoảng trắng bằng _
        - bỏ dấu tiếng Việt (cơ bản)
        """
        if not value:
            return ""
        normalized = value.strip().lower()
        # Thay khoảng trắng bằng _
        normalized = normalized.replace(" ", "_")
        return normalized
