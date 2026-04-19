# Kế hoạch mở rộng LexMind sang đa văn bản luật

**Mục tiêu:** Mở rộng hệ thống từ domain xử phạt (`Nghị định 168/2024/NĐ-CP`) sang đa văn bản gồm `Luật Đường bộ` và `Luật Trật tự, An toàn giao thông đường bộ`, hỗ trợ các câu hỏi về quy định, định nghĩa, nguyên tắc, quyền/nghĩa vụ và tham chiếu điều khoản cụ thể.

**Phạm vi:** Graph đã được kiểm soát và import sẵn. Plan này tập trung hoàn toàn vào **pipeline AI** — từ rewrite, retrieval, ranking đến generation và eval.

**Vấn đề cốt lõi:** Hệ thống hiện tại không phải là "không hỗ trợ node luật", mà là toàn bộ pipeline từ rewrite → retrieval strategy → ranking → context metadata đang thiên quá mạnh về bài toán xử phạt theo mô hình `Action → Article → Consequence`. Việc chỉ thêm node vào graph mà không sửa pipeline sẽ không giải quyết được vấn đề.

---

## 1. Rewrite Node

### Task 1.1 — Mở rộng entity schema và thêm `query_mode`
- **Mô tả:**
  Rewrite hiện tại chỉ bóc tách `{violation, vehicle_type, subject, conditions}`, ngầm assume mọi câu hỏi đều về vi phạm/xử phạt. Câu hỏi kiểu "đất của đường bộ là gì" hoặc "điều 13 khoản 1 điểm a quy định gì" sẽ không tạo được entity hữu ích, làm graph traversal branch gần như vô dụng.

  Cần mở rộng entity schema thành 2 mode rõ ràng:

  **`penalty_lookup`** — câu hỏi về mức phạt/hậu quả/vi phạm (giữ nguyên hành vi hiện tại):
  ```json
  {
    "query_mode": "penalty_lookup",
    "violation": "không đội mũ bảo hiểm",
    "vehicle_type": "xe máy",
    "subject": "người điều khiển",
    "conditions": []
  }
  ```

  **`provision_lookup`** — câu hỏi về quy định/định nghĩa/điều khoản:
  ```json
  {
    "query_mode": "provision_lookup",
    "legal_concept": "đất của đường bộ",
    "document_ref": null,     // optional - chỉ fill khi user chỉ định văn bản cụ thể
    "article_ref": null       // optional - chỉ fill khi user hỏi điều/khoản/điểm cụ thể
  }
  ```

  **Ví dụ các trường hợp:**
  - "đất của đường bộ là gì?" → chỉ có `legal_concept`, `document_ref` và `article_ref` = null
  - "đất của đường bộ là gì theo luật đường bộ?" → có `legal_concept` + `document_ref: "l35_2024"`
  - "điều 13 khoản 1 điểm a quy định gì?" → có `article_ref` đầy đủ, `legal_concept` có thể null
  - "điều 13 luật đường bộ nói về gì?" → có `document_ref` + `article_ref` (chỉ article, không có clause/point)

  Các signal nhận diện `provision_lookup`:
  - Có từ khóa `là gì`, `gồm những gì`, `bao gồm`, `định nghĩa`, `nguyên tắc`, `quy định về`
  - Có tham chiếu điều/khoản/điểm rõ ràng
  - Có tên văn bản cụ thể (`luật đường bộ`, `luật trật tự`)
  - Không có `violation` hoặc `vehicle_type`

  **Lưu ý:** `document_ref` và `article_ref` là optional. Chỉ fill khi user nói rõ ràng. Câu hỏi định nghĩa đơn giản không cần ép phải có văn bản cụ thể.

- **File cần sửa:**
  - `ai-service/app/prompts/rewrite.yaml` — mở rộng prompt nhận diện intent, thêm few-shot cho `provision_lookup`
  - `ai-service/app/nodes/rewrite.py` — parse và validate entity schema mới
  - `ai-service/app/core/state.py` — thêm comment/type hint cho `query_mode`, `legal_concept`, `document_ref`, `article_ref`
- **Độ ưu tiên:** P0

### Task 1.2 — Parse tham chiếu điều/khoản/điểm thành `article_ref`
- **Mô tả:**
  Khi user hỏi "điểm a khoản 1 điều 13 luật đường bộ", rewrite phải parse thành structured `article_ref` để có thể build exact node id thay vì dùng fulltext.

  Logic build id (chỉ thêm tiền tố `{doc_ref}_` trước ID cũ):
  ```python
  def build_node_id(doc_ref, article, clause=None, point=None):
      if clause:
          parts = [doc_ref, f"d{article}", f"k{clause}"]
          if point: parts.append(point)
      else:
          parts = [doc_ref, f"dieu_{article}"]
      return "_".join(parts)
  # Chỉ điều:           "l35_2024" + article=13               → "l35_2024_dieu_13"
  # Điều + khoản:      "nd168_2024" + article=7 + clause=7    → "nd168_2024_d7_k7"
  # Điều + khoản + điểm: "nd168_2024" + article=7 + clause=7 + point=c → "nd168_2024_d7_k7_c"
  ```

  Exact match chính xác hơn fulltext rất nhiều cho câu hỏi tra cứu cụ thể.
- **File cần sửa:**
  - `ai-service/app/nodes/rewrite.py`
  - `ai-service/app/prompts/rewrite.yaml`
- **Độ ưu tiên:** P0

---

## 2. Retrieval Layer

### Task 2.1 — Thêm `_search_provision()` branch trong graph retrieval
- **Mô tả:**
  Hiện `graph_retrieval.py` chỉ có `_search_graph()` dùng `Action` node làm entry point — hoàn toàn không phù hợp cho câu hỏi định nghĩa/quy định. Cần thêm branch riêng.

  **Trường hợp 1 — Tìm theo khái niệm** (fulltext trên `Article`, `Definition`, `Chapter`):
  ```cypher
  CALL db.index.fulltext.queryNodes('legal_fulltext_index', $keyword)
  YIELD node, score
  WHERE 'Article' IN labels(node) OR 'Definition' IN labels(node) OR 'Chapter' IN labels(node)
  WITH node, score ORDER BY score DESC LIMIT $top_k
  OPTIONAL MATCH (node)-[r]-(related)
  WHERE type(r) IN ['THUOC', 'QUY_DINH_TAI', 'GIAI_THICH', 'THAM_CHIEU_DEN']
  RETURN
    node.id AS id, node.text AS text, node.raw_text AS raw_content,
    node.doc_ref AS doc_ref, node.source_title AS source_title,
    node.source_type AS source_type, node.path AS path,
    labels(node)[0] AS label,
    collect(DISTINCT {
      rel_type: type(r), related_id: related.id, related_text: related.text
    }) AS relationships,
    score, 'provision' AS source
  ORDER BY score DESC
  ```

  **Trường hợp 2 — Exact match theo `article_ref`** (ưu tiên cao hơn nếu có):
  ```cypher
  MATCH (n {id: $article_id})
  OPTIONAL MATCH (n)-[r]-(related)
  WHERE type(r) IN ['THUOC', 'QUY_DINH_TAI', 'GIAI_THICH']
  RETURN n.id AS id, n.text AS text, n.raw_text AS raw_content,
         n.doc_ref AS doc_ref, n.source_title AS source_title,
         n.source_type AS source_type, n.path AS path,
         labels(n)[0] AS label,
         collect(DISTINCT { rel_type: type(r), related_id: related.id }) AS relationships,
         1.0 AS score, 'exact' AS source
  ```
- **File cần sửa:**
  - `ai-service/app/tools/graph_retrieval.py` — thêm `_CYPHER_PROVISION`, `_search_provision()`
- **Độ ưu tiên:** P0

### Task 2.2 — Phân nhánh `_arun()` theo `query_mode`
- **Mô tả:**
  Hiện `_arun()` luôn chạy song song tất cả branch kể cả `consequence-first` và `vehicle-aware boost`. Cần tách theo mode:

  ```python
  query_mode = entities.get("query_mode", "penalty_lookup")

  if query_mode == "provision_lookup":
      graph_task = search_with_timeout(
          self._search_provision(query, entities), self.graph_timeout, "Provision"
      )
      consequence_task = asyncio.sleep(0, result=[])  # bỏ consequence-first
  else:
      graph_task = search_with_timeout(
          self._search_graph(entities), self.graph_timeout, "Graph"
      )
      consequence_task = search_with_timeout(
          self._search_consequence_first(query, entities),
          self.consequence_timeout, "ConsequenceFirst"
      )
  ```

  Với `provision_lookup`, nếu `article_ref` có đủ thông tin thì ưu tiên exact match trước fulltext.
- **File cần sửa:**
  - `ai-service/app/tools/graph_retrieval.py`
  - `ai-service/app/nodes/retriever.py` nếu logic phân nhánh nằm ở đây
- **Độ ưu tiên:** P0

### Task 2.3 — Thêm filter và boost theo `doc_ref`
- **Mô tả:**
  Khi rewrite detect được `document_ref`, retrieval nên boost node có `doc_ref` khớp.

  Trong Cypher provision search:
  ```cypher
  WHERE ($doc_ref IS NULL OR node.doc_ref = $doc_ref)
  ```

  Trong RRF merge:
  ```python
  if document_ref and node["doc_ref"] == document_ref:
      score *= 1.2  # boost nhẹ, không force filter hoàn toàn
  ```
- **File cần sửa:**
  - `ai-service/app/tools/graph_retrieval.py`
- **Độ ưu tiên:** P0

### Task 2.4 — Lọc `action_`/`hv_` node khỏi candidate pool cho `provision_lookup`
- **Mô tả:**
  Từ eval baseline, các node `action_` và `hv_` đang rank cao không mong muốn trong RRF. Với câu hỏi định nghĩa/nguyên tắc, các node này là nhiễu thuần túy.

  ```python
  if query_mode == "provision_lookup":
      candidates = [
          c for c in candidates
          if not (c["id"].startswith("action_") or c["id"].startswith("hv_"))
      ]
  ```
- **File cần sửa:**
  - `ai-service/app/tools/graph_retrieval.py`
  - `ai-service/app/services/rag_service.py`
- **Độ ưu tiên:** P0

### Task 2.5 — Cập nhật fulltext index và tạo property index mới
- **Mô tả:**
  Mở rộng fulltext index để cover label mới. **Lưu ý:** Nodes mới không còn property `name`, chỉ có `text` và `raw_text`.
  ```cypher
  CREATE FULLTEXT INDEX legal_fulltext_index IF NOT EXISTS
  FOR (n:Article|Action|Consequence|Condition|Subject|Definition|Chapter)
  ON EACH [n.text, n.raw_text]
  ```

  > ⚠️ Index hiện tại trong code đang dùng `[n.name, n.text, n.raw_text]` — cần bỏ `n.name` vì nodes mới không có property này.

  Thêm property index cho filter nhanh:
  ```cypher
  CREATE INDEX idx_doc_ref IF NOT EXISTS FOR (n:Article) ON (n.doc_ref)
  CREATE INDEX idx_status  IF NOT EXISTS FOR (n:Article) ON (n.status)
  CREATE INDEX idx_doc_ref_status IF NOT EXISTS FOR (n:Article) ON (n.doc_ref, n.status)
  ```
- **File cần sửa:**
  - `ai-service/app/tools/graph_retrieval.py` — `_ensure_fulltext_index()`: bỏ `n.name`, thêm label `Chapter`
  - `ai-service/scripts/` — script Cypher migration riêng
- **Độ ưu tiên:** P0

---

## 3. Context Formatting

### Task 3.1 — Đưa `doc_ref`, `source_title`, `path` vào XML context
- **Mô tả:**
  Hiện `_format_context()` không include `doc_ref`. LLM không biết đoạn trích thuộc văn bản nào, dễ trích nhầm tên.

  **Node format mới đã có sẵn `source_title` và `path` trên mỗi node** → không cần `DOC_TITLE_MAP` dict tĩnh, đọc trực tiếp từ Cypher result.

  Sửa Cypher queries (keyword, vector, graph, consequence) thêm:
  ```cypher
  RETURN
    ...
    node.doc_ref       AS doc_ref,
    node.source_title  AS source_title,
    node.source_type   AS source_type,
    node.path          AS path,
    ...
  ```

  Sửa XML output trong `_format_context()`:
  ```xml
  <source id="l35_2024_dieu_13" score="0.031" label="Article" from="keyword,vector">
    <doc_ref>l35_2024</doc_ref>
    <source_title>Luật Đường bộ 2024</source_title>
    <path>Chương I > Điều 13 > Khoản 1 > Điểm a</path>
    <content>a) Đất của đường bộ gồm phần đất để xây dựng công trình đường bộ...</content>
    <relationships>...</relationships>
  </source>
  ```

  Đồng thời bỏ `node.name` / `related.name` khỏi tất cả Cypher queries vì nodes mới không có property `name`. Thay thế bằng `node.text` / `related.text`.

- **File cần sửa:**
  - `ai-service/app/tools/graph_retrieval.py` — tất cả `_CYPHER_*` queries và `_format_context()`
- **Độ ưu tiên:** P0

---

## 4. LangGraph Pipeline

### Task 4.1 — Update Router mở rộng scope domain
- **Mô tả:**
  `router_classify.yaml` đang hard-code scope `Decree 168/2024/NĐ-CP` và reject `other laws`. Cần đổi:
  - **Trong domain:** ND168 + Luật Đường bộ + Luật Trật tự ATGT
  - **Out-of-domain:** lĩnh vực pháp luật khác không liên quan giao thông đường bộ
  - Không được reject câu hỏi quy định/định nghĩa/nguyên tắc giao thông chỉ vì không nhắc đến xử phạt
- **File cần sửa:**
  - `ai-service/app/prompts/router_classify.yaml`
  - `ai-service/app/nodes/router.py` nếu cần thêm route metadata
- **Độ ưu tiên:** P0

### Task 4.2 — Update Reflector tách logic đánh giá theo `query_mode`
- **Mô tả:**
  Reflector hiện hard-code penalty keywords (`phạt tiền`, `trừ điểm`, `tước quyền`) để đánh giá đủ context. Với câu hỏi định nghĩa/quy định, những keyword này không liên quan → trigger `not_found` nhầm.

  Tách logic:
  - `penalty_lookup` → giữ nguyên penalty keyword check
  - `provision_lookup` → đánh giá dựa trên: có `Article`/`Definition` node trong context không, `doc_ref` có khớp không, `raw_text` có chứa term từ `legal_concept` không
- **File cần sửa:**
  - `ai-service/app/nodes/reflector.py`
  - `ai-service/app/prompts/reflector.yaml`
- **Độ ưu tiên:** P0

### Task 4.3 — Update Generator/Synthesis cho đa văn bản
- **Mô tả:**
  `synthesis.yaml` đang hard-code `Nghị định 168/2024/NĐ-CP`. Cần mở rộng:
  - Trích dẫn tên văn bản động từ `doc_title` trong context
  - Hỗ trợ answer dạng định nghĩa: "Theo [doc_title], [khái niệm] là..."
  - Hỗ trợ answer dạng nguyên tắc/quy định không ép về xử phạt
  - Giữ format penalty khi `penalty_lookup`
  - Thêm few-shot cho id dạng `l35_2024_d4_k1_a`
- **File cần sửa:**
  - `ai-service/app/prompts/synthesis.yaml`
  - `ai-service/app/prompts/synthesis_compact.yaml`
  - `ai-service/app/nodes/generator.py`
- **Độ ưu tiên:** P0

### Task 4.4 — Clarify behavior mở rộng cho `provision_lookup`
- **Mô tả:**
  Bổ sung trigger clarify:
  - User hỏi "theo luật nào" khi nhiều văn bản liên quan
  - Câu hỏi quá rộng ("quy định về tốc độ") cần thêm ngữ cảnh
  - Thuật ngữ có nhiều biến thể

  Không clarify khi retrieval đã có `Definition` hoặc `Article` rõ ràng.
- **File cần sửa:**
  - `ai-service/app/nodes/reflector.py`
  - `ai-service/app/prompts/reflector.yaml`
- **Độ ưu tiên:** P1

### Task 4.5 — Bổ sung metadata nguồn trong streaming response
- **Mô tả:**
  Thêm vào metadata streaming: `doc_ref`, `doc_title`, `status`, `effective_date`, `query_mode`.
  Giúp UI hiển thị đúng nguồn và eval kiểm tra văn bản có còn hiệu lực không.
- **File cần sửa:**
  - `ai-service/app/graph/streaming.py`
  - `ai-service/app/api/routes.py`
- **Độ ưu tiên:** P1

---

## 5. ID Format Migration

### Task 5.1 — Cập nhật regex và references cho ID format mới
- **Mô tả:**
  Node IDs đã thay đổi từ format cũ không có tiền tố (`d7_k7_c`, `dieu_7`) sang format mới có tiền tố `{doc_ref}_` (`nd168_2024_d7_k7_c`, `l35_2024_dieu_13`).
  Phần sau tiền tố giữ nguyên format cũ: `dieu_N` (chỉ điều), `dN_kN` (điều+khoản), `dN_kN_x` (điều+khoản+điểm).
  Toàn bộ code đang hardcode regex/pattern không có tiền tố cần cập nhật.

  **Các file bị ảnh hưởng:**

  **1. `source_parser.py` — `_RE_ENTITY_ID` regex:**
  ```python
  # CŨ — chỉ match d18_k8_a (không có tiền tố doc_ref)
  _RE_ENTITY_ID = re.compile(
      r"\b(d(\d+)(?:_k(\d+))?(?:_([a-zđ]+))?)\b"
  )

  # MỚI — thêm optional prefix {doc_ref}_
  # Match: nd168_2024_d7_k7_c, l35_2024_dieu_13, d7_k7_c (backward-compat)
  _RE_ENTITY_ID = re.compile(
      r"\b((?:[a-z]\w+_\d{4}_)?(?:dieu_(\d+)|d(\d+)(?:_k(\d+)(?:_([a-zđ]+))?)?))\b"
  )
  ```
  Logic parse giữ nguyên: `d{N}` → `Điều {N}`, `k{N}` → `Khoản {N}`, `{letter}` → `Điểm {letter}`.

  **2. `eval/evaluation/target.py` — `_RE_ALLOWED_GRADING_NODE_ID` whitelist:**
  ```python
  # CŨ — chỉ whitelist dieu_7, d7_k7, d7_k7_c
  _RE_ALLOWED_GRADING_NODE_ID = re.compile(
      r"^(?:dieu_\d+|d\d+(?:_k\d+(?:_[\wđ]+)?)?|k\d+_k\d+(?:_[\wđ]+)?)$"
  )

  # MỚI — thêm optional prefix {doc_ref}_
  _RE_ALLOWED_GRADING_NODE_ID = re.compile(
      r"^(?:[a-z]\w+_\d{4}_)?(?:dieu_\d+|d\d+(?:_k\d+(?:_[\wđ]+)?)?)$"
  )
  ```

  **3. `synthesis.yaml` — Few-shot examples và PARSING RULES:**
  - Các examples dùng `[d6_k3_p]`, `[d7_k2_c]` → đổi sang `[nd168_2024_d6_k3_p]`, `[nd168_2024_d7_k2_c]`
  - Hardcoded `Nghị định 168/2024/NĐ-CP` → đọc từ `<source_title>` trong context XML
  - Pattern matching rules giữ nguyên (`d{số}` → `Điều {số}`), chỉ thêm hướng dẫn bỏ tiền tố `{doc_ref}_` trước khi parse
  - Few-shot examples cho `provision_lookup` (thêm mới, dạng "Theo [source_title], [khái niệm] là...")

  **4. `eval/service.py` — Comments/regex (nếu có):**
  - Cập nhật comments mô tả format ID mới
  - Kiểm tra regex parse có reuse từ `target.py` hay tự define riêng

  **5. `eval/dataset/*.json` — Test dataset:**
  - Cập nhật `reference_nodes` trong dataset eval sang format mới
  - VD: `"reference_nodes": ["d7_k7_c"]` → `"reference_nodes": ["nd168_2024_d7_k7_c"]`

- **File cần sửa:**
  - `ai-service/app/services/source_parser.py` — `_RE_ENTITY_ID`, logic parse
  - `ai-service/app/eval/evaluation/target.py` — `_RE_ALLOWED_GRADING_NODE_ID`
  - `ai-service/app/prompts/synthesis.yaml` — few-shot examples, pattern rules
  - `ai-service/app/prompts/synthesis_compact.yaml` — tương tự
  - `ai-service/app/eval/service.py` — comments
  - `ai-service/test/dataset/*.json` — reference_nodes
- **Độ ưu tiên:** P0


## Thứ tự triển khai

### Phase 0 — Foundation: ID Format + Index
```
Task 5.1  Cập nhật regex/references cho ID format mới
Task 2.5  Tạo index mới (Definition, doc_ref, status)
```

### Phase 1 — Core Pipeline: Rewrite + Retrieval
```
Task 1.1  Mở rộng entity schema + query_mode trong rewrite
Task 1.2  Parse article_ref từ câu hỏi (format mới)
Task 2.1  Thêm _search_provision() branch
Task 2.2  Phân nhánh _arun() theo query_mode
Task 2.3  Filter + boost doc_ref trong retrieval
Task 2.4  Lọc action_/hv_ node cho provision_lookup
Task 3.1  Đưa doc_ref + source_title vào XML context
```

### Phase 2 — LangGraph Nodes: Router + Reflector + Generator
```
Task 4.1  Router mở rộng domain scope
Task 4.2  Reflector tách logic theo query_mode
Task 4.3  Generator/Synthesis đa văn bản
```

### Phase 3 — Polish (Optional)
```
Task 4.4  Clarify behavior mở rộng
Task 4.5  Metadata streaming
```

---

## Rủi ro kỹ thuật

- **Không sửa rewrite** → pipeline vẫn cố bẻ câu hỏi định nghĩa về `Action`, graph traversal vô dụng với luật mới.
- **Không tách `_arun()` theo mode** → `consequence-first` và `vehicle boost` tiếp tục nhiễu với mọi câu hỏi.
- **Không thêm `doc_ref` vào context** → Generator không biết trích dẫn từ văn bản nào, dễ nhầm tên.
- **Không migrate ID format** → `source_parser.py` không parse được ID mới → anchor pháp lý trống; `_RE_ALLOWED_GRADING_NODE_ID` reject toàn bộ node mới → eval luôn fail retrieval metrics; `synthesis.yaml` few-shot dạy format cũ → LLM output trích dẫn sai.