# AI Service - FastAPI RAG Pipeline 🤖

AI Service là trái tim của hệ thống Chatbot Luật, triển khai **RAG (Retrieval-Augmented Generation) Pipeline** tiên tiến với **LangGraph**, **Neo4j Knowledge Graph**, **Web Search**, và **Semantic Caching**.

## 📑 Mục lục

- [✨ Tính năng chính](#-tính-năng-chính)
- [🏗️ Kiến trúc tổng quan](#️-kiến-trúc-tổng-quan)
- [🛠️ Tech Stack](#️-tech-stack)
- [📂 Cấu trúc thư mục](#-cấu-trúc-thư-mục)
- [🔍 4-Prong Retrieval Strategy](#-4-prong-retrieval-strategy)
- [🤖 LangGraph State Machine](#-langgraph-state-machine)
- [🌐 Web Search Integration](#-web-search-integration)
- [⚡ Semantic Caching](#-semantic-caching)
- [📊 Prompts & System Instructions](#-prompts--system-instructions)
- [🚀 API Endpoints](#-api-endpoints)
- [⚙️ Configuration](#️-configuration)
- [🧪 Testing & Evaluation](#-testing--evaluation)
- [🔧 Troubleshooting](#-troubleshooting)

---

## ✨ Tính năng chính

### 🎯 RAG Pipeline Features

- **4-Prong Retrieval Strategy**: Kết hợp 4 phương pháp tìm kiếm song song
  - Vector Search (Semantic similarity)
  - Keyword Search (Fulltext index)
  - Graph Traversal (Relationship following)
  - Consequence-first Lookup (Penalty → Law reverse search)

- **Reciprocal Rank Fusion (RRF)**: Merge kết quả từ 4 nguồn với scoring thông minh

- **Vehicle-Aware Boosting**: Tự động phát hiện loại phương tiện và boost kết quả phù hợp

### 🧠 LLM Orchestration

- **Multi-level Reasoning**: Điều chỉnh "thinking budget" dựa trên độ phức tạp câu hỏi
  - Level 1 (Simple): No thinking budget
  - Level 2 (Medium): 2048 token thinking budget  
  - Level 3 (Complex): 4096 token thinking budget

- **Context-Aware Response**: Tự động nhận biết và chuyển đổi giữa 2 styles:
  - **Legal**: Chính xác, chuẩn mực, có trích dẫn điều luật
  - **Natural**: Thân thiện, dễ hiểu, conversational

- **Reflection & Self-Correction**: LLM tự kiểm tra và cải thiện câu trả lời

### ⚡ Performance Optimization

- **Semantic Caching**: Redis Stack với RediSearch similarity search
- **Async/Await**: Tất cả I/O operations đều async
- **Connection Pooling**: PostgreSQL async pool cho checkpoints
- **Parallel Execution**: 4 prong searches chạy đồng thời

### 📊 Observability

- **LangSmith Tracing**: Optional tracing cho debugging (nếu bật)
- **LangSmith Evaluation**: Track metrics (faithfulness, relevancy, etc.)
- **AI Metrics**: Token count, latency, cost estimation
- **Health Checks**: `/health` và `/debug` endpoints

---

## 🏗️ Kiến trúc tổng quan

```text
┌────────────────────────────────────────────────────────────────┐
│                    FastAPI Application                         │
│                      (Port 8001)                               │
└────────────┬───────────────────────────────────────────────────┘
             │
             ├─── API Layer (routes.py)
             │    ├── POST /ask/stream
             │    ├── POST /conversations/generate-title
             │    ├── DELETE /conversations/{id}/checkpoints
             │    ├── GET /law-detail/{node_id}
             │    ├── GET /health, /debug
             │    └── DELETE /cache
             │
             ├─── Services Layer
             │    └── RAGService (rag_service.py)
             │         └── LangGraph State Machine
             │              ├── Router Node
             │              ├── Natural Agent Node
             │              ├── Legal Agent Node
             │              ├── Reflector Node
             │              └── Synthesis Node
             │
             ├─── Tools Layer
             │    ├── GraphRetrieval (graph_retrieval.py)
             │    │    ├── Vector Search
             │    │    ├── Keyword Search
             │    │    ├── Graph Traversal
             │    │    └── Consequence-first
             │    └── WebSearch (web_search.py)
             │         ├── Serper.dev
             │         └── Firecrawl
             │
             ├─── Cache Layer
             │    └── SemanticCache (semantic_cache.py)
             │         └── Redis Stack (RediSearch)
             │
             ├─── Core Layer
             │    ├── Config (config.py)
             │    ├── State (state.py)
             │    └── Checkpoint (checkpoint.py)
             │         └── AsyncPostgresSaver
             │
             └─── External Dependencies
                  ├── Neo4j Driver (async)
                  ├── Google Gemini API
                  ├── Redis Stack
                  └── PostgreSQL
```

### LangGraph State Flow

```text
                 ┌─────────────┐
                 │   START     │
                 └──────┬──────┘
                        │
                        ▼
              ┌─────────────────┐
              │  Check Cache    │ ◀────────────────┐
              └────────┬────────┘                  │
                       │                           │
           ┌───────────┴───────────┐              │
           ▼                       ▼              │
       Hit (>0.9)              Miss (<0.9)        │
           │                       │              │
           │                       ▼              │
           │              ┌─────────────────┐    │
           │              │     Router      │    │
           │              │  (Classify +    │    │
           │              │   Rewrite)      │    │
           │              └────────┬────────┘    │
           │                       │              │
           │         ┌─────────────┴─────────────┐
           │         ▼                           ▼
           │   ┌────────────┐            ┌────────────┐
           │   │  Natural   │            │   Legal    │
           │   │  Agent     │            │   Agent    │
           │   │(Casual Q&A)│            │(LawSearch) │
           │   └────────────┘            └──────┬─────┘
           │         │                          │
           │         │                          ▼
           │         │                   ┌────────────┐
           │         │                   │   Tools    │
           │         │                   │ - Neo4j    │◀────┐
           │         │                   │ - Web      │     │
           │         │                   └──────┬─────┘     │
           │         │                          │           │
           │         │                (Insufficient?)       │
           │         │                          └───────────┘
           │         │                          
           │         └──────────┬───────────────┘
           │                    ▼
           │           ┌─────────────────┐
           │           │   Reflector     │
           │           │ (Validate +     │
           │           │  Self-correct)  │
           │           └────────┬────────┘
           │                    │
           │                    ▼
           │           ┌─────────────────┐
           │           │   Synthesis     │
           │           │ (Format +       │
           │           │  Citations)     │
           │           └────────┬────────┘
           │                    │
           └────────────────────┴─────────────▶ Store Cache
                                │
                                ▼
                         ┌─────────────┐
                         │     END     │
                         └─────────────┘
```

---

## 🛠️ Tech Stack

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Framework** | FastAPI | 0.115.9 | High-performance async API |
| **LLM** | Google Gemini 2.5 Flash | Latest | Text generation với thinking mode |
| **Orchestration** | LangGraph | 1.0.9 | Agentic workflow state machine |
| **LangChain** | langchain-google-genai | Latest | LLM integration |
| **Knowledge Graph** | Neo4j (async driver) | 5.28.1 | Structured legal data |
| **Embeddings** | SentenceTransformers | 4.1.0 | Vietnamese embeddings (vietnamese-sbert) |
| **Cache** | Redis Stack | 5.10.0 | Semantic similarity search (RediSearch) |
| **State Persistence** | AsyncPostgresSaver | 4.0.0 | Conversation checkpoints |
| **Web Search** | Serper.dev SDK | Latest | Google search API |
| **Web Scraping** | Firecrawl | Latest | Clean web content extraction |
| **Config** | Pydantic Settings | 2.9.1 | Type-safe configuration |
| **Server** | Uvicorn | Latest | ASGI server |

---

## 📂 Cấu trúc thư mục

```text
ai-service/
├── main.py                              # Entry point, lifespan management
├── requirements.txt                     # Python dependencies
├── pip_list.json                        # Frozen dependency versions
├── .env                                 # Environment variables (gitignored)
│
├── app/
│   ├── __init__.py
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py                    # All API endpoints
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py                    # Pydantic Settings (env vars)
│   │   ├── checkpoint.py                # AsyncPostgresSaver setup
│   │   └── state.py                     # RAGState TypedDict schema
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   └── rag_service.py               # Main RAG pipeline + LangGraph
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── graph_retrieval.py           # 4-prong Neo4j search + RRF
│   │   └── web_search.py                # Serper + Firecrawl integration
│   │
│   ├── cache/
│   │   ├── __init__.py
│   │   └── semantic_cache.py            # Redis semantic caching
│   │
│   ├── prompts/                         # YAML-based system prompts
│   │   ├── synthesis.yaml               # Legal style synthesis
│   │   ├── synthesis_natural.yaml       # Natural conversational style
│   │   ├── router_rewrite.yaml          # Query classification & rewriting
│   │   ├── reflector.yaml               # Answer quality validation
│   │   ├── analyzer.yaml                # Entity extraction
│   │   └── title_generator.yaml         # Conversation title generation
│   │
│   ├── agent-skills/                    # Markdown-based reasoning guides
│   │   ├── 01_graph_analyzer.skill.md
│   │   └── 02_citation_validator.skill.md
│   │
│   └── eval/                            # RAGAS evaluation pipeline
│       ├── __init__.py
│       ├── service.py                   # Evaluation service
│       └── migrations.py                # Eval DB migrations
│
└── test/                                # Test suite
    ├── __init__.py
    └── test_*.py
```

---

## 🔍 4-Prong Retrieval Strategy

Hệ thống sử dụng **4 chiến lược tìm kiếm song song** và merge kết quả bằng **Reciprocal Rank Fusion (RRF)**.

### 1. Vector Search (Semantic Similarity)

```python
# Tìm kiếm dựa trên embedding similarity
MATCH (n)
WHERE n.embedding IS NOT NULL
WITH n, vector.similarity.cosine(n.embedding, $query_embedding) AS score
WHERE score > 0.6
RETURN n
ORDER BY score DESC
LIMIT 10
```

**Ưu điểm:** Hiểu được ngữ nghĩa, tìm được nội dung tương tự về mặt ý nghĩa  
**Nhược điểm:** Có thể bỏ sót các từ khóa chính xác

### 2. Keyword Search (Fulltext Index)

```python
# Tìm kiếm chính xác từ khóa
CALL db.index.fulltext.queryNodes("lawFulltext", $query_text)
YIELD node, score
WHERE score > 1.0
RETURN node
ORDER BY score DESC
LIMIT 10
```

**Ưu điểm:** Tìm chính xác các từ khóa pháp lý (số hiệu điều, mức phạt)  
**Nhược điểm:** Không hiểu ngữ nghĩa

### 3. Graph Traversal (Relationship Following)

```python
# Duyệt theo quan hệ trong graph
MATCH (start)-[r:RELATED_TO|APPLIES_TO|REGULATES*1..2]-(related)
WHERE start.id IN $initial_node_ids
RETURN DISTINCT related
LIMIT 10
```

**Ưu điểm:** Tìm được thông tin liên quan qua cấu trúc quan hệ  
**Nhược điểm:** Phụ thuộc vào chất lượng graph schema

### 4. Consequence-First Lookup (Reverse Search)

```python
# Tìm từ hậu quả (mức phạt) ngược về nguyên nhân (hành vi vi phạm)
MATCH (penalty:Penalty)-[:REGULATED_BY]->(article:Article)
WHERE penalty.amount CONTAINS $penalty_keyword
  OR penalty.description CONTAINS $query_text
RETURN article, penalty
LIMIT 10
```

**Ưu điểm:** Hiệu quả cho câu hỏi dạng "bị phạt bao nhiêu nếu..."  
**Nhược điểm:** Chỉ áp dụng cho legal domain có cấu trúc rõ ràng

### Reciprocal Rank Fusion (RRF)

```python
def rrf_score(rank: int, k: int = 60) -> float:
    """
    RRF scoring formula
    k=60 là giá trị thường dùng trong literature
    """
    return 1.0 / (k + rank)

# Merge scores từ 4 prongs
final_score = (
    rrf_score(vector_rank) +
    rrf_score(keyword_rank) +
    rrf_score(graph_rank) +
    rrf_score(consequence_rank)
)
```

### Vehicle-Aware Boosting

```python
# Tự động phát hiện loại phương tiện trong câu hỏi
vehicle_patterns = {
    "xe máy": ["motorbike", "motorcycle"],
    "ô tô": ["car", "automobile"],
    "xe tải": ["truck"],
    "xe khách": ["bus", "coach"]
}

# Boost score nếu match vehicle type
if detected_vehicle_type == node.vehicle_type:
    score *= 1.5
```

---

## 🤖 LangGraph State Machine

### RAGState Schema

```python
from typing import TypedDict, Annotated, Sequence
from langgraph.graph import add_messages

class RAGState(TypedDict):
    # Input
    messages: Annotated[Sequence, add_messages]  # Conversation history
    question: str                                 # Current user question
    conversation_id: str                          # Thread ID
    
    # Routing
    response_style: str                           # "legal" | "natural"
    query_rewritten: str                          # Rewritten query
    complexity_level: int                         # 1=simple, 2=medium, 3=complex
    
    # Retrieval
    retrieved_docs: list[dict]                    # From Neo4j/Web
    sources: list[dict]                           # URLs, citations
    
    # Reasoning
    thought: str                                  # LLM's thinking process
    intermediate_steps: list                      # Tool calls log
    
    # Validation
    needs_more_info: bool                         # Reflector decision
    reflection_feedback: str                      # What's missing
    
    # Output
    answer: str                                   # Final answer
    confidence_score: float                       # 0.0 - 1.0
    
    # Metrics
    cache_hit: bool
    tokens_used: dict
```

### Nodes trong LangGraph

#### 1. Router Node

```python
async def router_node(state: RAGState) -> RAGState:
    """
    Phân loại câu hỏi và rewrite query
    Output: response_style, query_rewritten, complexity_level
    """
    prompt = load_prompt("router_rewrite.yaml")
    result = await llm.ainvoke(prompt.format(question=state["question"]))
    
    return {
        "response_style": result["style"],      # "legal" or "natural"
        "query_rewritten": result["rewritten"], # Optimized query
        "complexity_level": result["level"]     # 1, 2, or 3
    }
```

**Ví dụ:**
- Input: "Không đội mũ bảo hiểm bị sao?"
- Output: 
  - `response_style="legal"`
  - `query_rewritten="Mức phạt vi phạm không đội mũ bảo hiểm theo Nghị định 168/2024"`
  - `complexity_level=2`

#### 2. Legal Agent Node

```python
async def legal_agent_node(state: RAGState) -> RAGState:
    """
    Xử lý câu hỏi pháp lý với tool calling
    Tools: graph_retrieval, web_search
    """
    tools = [graph_retrieval_tool, web_search_tool]
    agent = create_react_agent(llm, tools)
    
    result = await agent.ainvoke({
        "messages": state["messages"],
        "query": state["query_rewritten"]
    })
    
    return {
        "retrieved_docs": result["documents"],
        "sources": result["sources"],
        "thought": result["thinking"],
        "intermediate_steps": result["tool_calls"]
    }
```

#### 3. Natural Agent Node

```python
async def natural_agent_node(state: RAGState) -> RAGState:
    """
    Xử lý câu hỏi casual/chit-chat
    Không cần tools, trả lời trực tiếp
    """
    prompt = load_prompt("synthesis_natural.yaml")
    result = await llm.ainvoke(prompt.format(
        question=state["question"],
        history=state["messages"]
    ))
    
    return {
        "answer": result["response"],
        "thought": result["thinking"]
    }
```

#### 4. Reflector Node

```python
async def reflector_node(state: RAGState) -> RAGState:
    """
    Kiểm tra chất lượng câu trả lời
    Quyết định: accept hoặc retry với feedback
    """
    prompt = load_prompt("reflector.yaml")
    result = await llm.ainvoke(prompt.format(
        question=state["question"],
        retrieved_docs=state["retrieved_docs"],
        current_answer=state.get("answer", "")
    ))
    
    return {
        "needs_more_info": result["insufficient"],
        "reflection_feedback": result["feedback"],
        "confidence_score": result["confidence"]
    }
```

**Survival Rule:** Nếu không tìm thấy luật cụ thể, hệ thống sẽ:
1. Tìm luật gần nhất (similar violations)
2. Tham khảo web search
3. Nếu vẫn không có → Thừa nhận "chưa có quy định rõ ràng" thay vì bịa đặt

#### 5. Synthesis Node

```python
async def synthesis_node(state: RAGState) -> RAGState:
    """
    Format câu trả lời cuối cùng với citations
    Style: legal (formal) hoặc natural (friendly)
    """
    if state["response_style"] == "legal":
        prompt = load_prompt("synthesis.yaml")
    else:
        prompt = load_prompt("synthesis_natural.yaml")
    
    result = await llm.ainvoke(prompt.format(
        question=state["question"],
        retrieved_docs=state["retrieved_docs"],
        sources=state["sources"],
        thought=state["thought"]
    ))
    
    return {
        "answer": result["formatted_answer"]
    }
```

### Conditional Edges

```python
def should_continue(state: RAGState) -> str:
    """Routing logic"""
    if state.get("cache_hit"):
        return "end"
    
    if state["response_style"] == "natural":
        return "natural_agent"
    else:
        return "legal_agent"

def should_reflect(state: RAGState) -> str:
    """Reflection loop"""
    if state.get("needs_more_info") and state.get("retry_count", 0) < 2:
        return "legal_agent"  # Retry with feedback
    else:
        return "synthesis"    # Accept and format
```

---

## 🌐 Web Search Integration

### Serper.dev (Google Search API)

```python
async def serper_search(query: str, num_results: int = 5) -> list[dict]:
    """
    Google search qua Serper.dev API
    """
    url = "https://google.serper.dev/search"
    headers = {"X-API-KEY": settings.SERPER_API_KEY}
    payload = {
        "q": query,
        "num": num_results,
        "gl": "vn",  # Geo location: Vietnam
        "hl": "vi"   # Language: Vietnamese
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)
        results = response.json()
    
    return results["organic"]  # [{title, link, snippet}, ...]
```

### Firecrawl (Web Scraping)

```python
async def firecrawl_scrape(url: str) -> str:
    """
    Scrape và clean content từ URL
    Trả về markdown-formatted text
    """
    from firecrawl import FirecrawlApp
    
    app = FirecrawlApp(api_key=settings.FIRECRAWL_API_KEY)
    result = await app.scrape_url(url, params={
        "formats": ["markdown"],
        "onlyMainContent": True,  # Loại bỏ ads, sidebar
        "timeout": 10000
    })
    
    return result["markdown"]
```

### Combined Web Search Tool

```python
@tool
async def web_search_tool(query: str) -> str:
    """
    Tìm kiếm web và scrape nội dung
    """
    # Step 1: Search with Serper
    search_results = await serper_search(query, num_results=3)
    
    # Step 2: Scrape top results
    scraped_content = []
    for result in search_results[:2]:  # Only top 2 to save time
        try:
            content = await firecrawl_scrape(result["link"])
            scraped_content.append({
                "url": result["link"],
                "title": result["title"],
                "content": content[:2000]  # Limit to 2000 chars
            })
        except Exception as e:
            logger.warning(f"Failed to scrape {result['link']}: {e}")
    
    return scraped_content
```

**Use Cases:**
- Tìm tin tức cập nhật về luật mới
- Scrape nội dung từ trang chính phủ
- Fallback khi Knowledge Graph không có thông tin

---

## ⚡ Semantic Caching

### Redis Stack Setup

```bash
# Yêu cầu Redis Stack (not standard Redis)
docker run -d --name redis-stack \
  -p 6379:6379 \
  redis/redis-stack:latest
```

### Cache Architecture

```python
class SemanticCache:
    def __init__(self, redis_client, embedding_model):
        self.redis = redis_client
        self.embedder = embedding_model
        self.index_name = "question_cache"
        
        # Create RediSearch index for vector similarity
        self.create_index()
    
    async def get(self, question: str, threshold: float = 0.9) -> dict | None:
        """
        Tìm câu hỏi tương tự trong cache
        threshold: cosine similarity >= 0.9 → cache hit
        """
        # 1. Embed question
        query_embedding = await self.embedder.aembed_query(question)
        
        # 2. Vector search in Redis
        query = f"*=>[KNN 1 @embedding $vec AS score]"
        results = await self.redis.ft(self.index_name).search(
            query,
            query_params={"vec": query_embedding}
        )
        
        # 3. Check similarity threshold
        if results.docs and results.docs[0].score >= threshold:
            cached_data = json.loads(results.docs[0].answer)
            return cached_data
        
        return None
    
    async def set(self, question: str, answer: dict, ttl: int = 3600):
        """
        Cache câu trả lời với TTL (default 1 hour)
        """
        question_embedding = await self.embedder.aembed_query(question)
        
        cache_key = f"cache:{hashlib.md5(question.encode()).hexdigest()}"
        
        await self.redis.hset(cache_key, mapping={
            "question": question,
            "embedding": question_embedding.tobytes(),
            "answer": json.dumps(answer, ensure_ascii=False),
            "cached_at": datetime.now().isoformat()
        })
        
        await self.redis.expire(cache_key, ttl)
```

### Cache Hit Example

```text
User asks: "Không đội mũ bảo hiểm bị phạt bao nhiêu?"

1. Hash question → Embed with SentenceTransformer
2. RediSearch vector similarity search
3. Found similar cached question (score=0.93):
   "Không đội nón bảo hiểm bị phạt bao nhiêu tiền?"
4. Return cached answer immediately (no LLM call)

Result:
- Latency: ~10ms (vs ~2000ms with LLM)
- Cost: $0 (vs ~$0.002 per query)
- Cache Hit Rate: Typically 30-40% for common questions
```

---

## 📊 Prompts & System Instructions

Tất cả system prompts được lưu dưới dạng YAML trong `app/prompts/`:

### router_rewrite.yaml

```yaml
system: |
  Bạn là Router AI chuyên phân loại câu hỏi về luật giao thông Việt Nam.
  
  NHIỆM VỤ:
  1. Phân loại câu hỏi:
     - "legal": Câu hỏi về luật, quy định, mức phạt
     - "natural": Chào hỏi, cảm ơn, câu hỏi thường
  
  2. Rewrite câu hỏi thành query tối ưu cho tìm kiếm
  
  3. Đánh giá độ phức tạp (1-3):
     - Level 1: Câu hỏi đơn giản, trực tiếp
     - Level 2: Cần so sánh hoặc tổng hợp
     - Level 3: Phức tạp, nhiều điều kiện

examples:
  - input: "Xin chào"
    output:
      style: "natural"
      rewritten: "Xin chào"
      level: 1
  
  - input: "Không đội mũ bảo hiểm bị phạt bao nhiêu?"
    output:
      style: "legal"
      rewritten: "Mức phạt vi phạm không đội mũ bảo hiểm theo Nghị định 168/2024"
      level: 2
```

### synthesis.yaml (Legal Style)

```yaml
system: |
  Bạn là Chatbot Luật Giao Thông Việt Nam chuyên nghiệp.
  
  NGUYÊN TẮC TRẢ LỜI:
  1. Chính xác: Dựa HOÀN TOÀN vào tài liệu được cung cấp
  2. Trích dẫn: Luôn ghi rõ điều khoản, mức phạt cụ thể
  3. Cấu trúc: Dễ đọc với bullet points, bảng biểu
  4. Survival rule: Nếu không có thông tin → Thừa nhận thẳng thắn
  
  FORMAT:
  - Mức phạt: [số tiền cụ thể]
  - Hành vi vi phạm: [mô tả chi tiết]
  - Căn cứ pháp lý: [Điều X, Nghị định Y]
  - Nguồn: [URL nếu có]

template: |
  Câu hỏi: {question}
  
  Tài liệu tham khảo:
  {retrieved_docs}
  
  Suy luận:
  {thought}
  
  Hãy tổng hợp câu trả lời theo format trên.
```

### synthesis_natural.yaml (Natural Style)

```yaml
system: |
  Bạn là trợ lý AI thân thiện, giúp người dùng hiểu về luật giao thông.
  
  PHONG CÁCH:
  - Thân thiện, dễ hiểu
  - Dùng ngôn ngữ đời thường
  - Có thể dùng emoji 😊
  - Giữ chính xác về mặt pháp lý nhưng trình bày gần gũi

template: |
  Chào bạn! Mình là chatbot hỗ trợ về luật giao thông 👋
  
  {question}
  
  [Trả lời thân thiện, dễ hiểu]
```

### reflector.yaml

```yaml
system: |
  Bạn là AI Reflector, nhiệm vụ kiểm tra chất lượng câu trả lời.
  
  ĐÁNH GIÁ:
  1. Có đủ thông tin trả lời câu hỏi?
  2. Có mâu thuẫn giữa các nguồn?
  3. Có cần tìm kiếm thêm không?
  
  OUTPUT:
  - insufficient: true/false
  - feedback: Nếu insufficient=true, gợi ý cần tìm gì
  - confidence: 0.0-1.0

template: |
  Câu hỏi: {question}
  Retrieved Docs: {retrieved_docs}
  Current Answer: {current_answer}
  
  Phân tích:
```

---

## 🚀 API Endpoints

### POST /ask/stream

**Mô tả:** Core RAG pipeline với streaming response

**Headers:**
```
X-Internal-Secret: <secret>
Content-Type: application/json
```

**Request Body:**
```json
{
  "question": "Không đội mũ bảo hiểm bị phạt bao nhiêu?",
  "conversation_id": "uuid-string",
  "message_id": "uuid-string",
  "user_id": "uuid-string"
}
```

**Response:** NDJSON stream (newline-delimited JSON)

```json
{"type": "thought", "content": "Đang phân tích câu hỏi..."}
{"type": "thought", "content": "Tìm kiếm trong Knowledge Graph..."}
{"type": "answer", "content": "Theo Nghị định 168/2024..."}
{"type": "metadata", "sources": [{"url": "...", "title": "...", "citation": "..."}]}
{"type": "metrics", "tokens": {"input": 150, "output": 320}, "latency": 1850}
{"type": "done"}
```

**Stream Types:**
- `thought`: Quá trình suy luận của LLM
- `answer`: Câu trả lời (có thể stream nhiều chunks)
- `metadata`: Sources, citations
- `metrics`: Token usage, latency
- `done`: End of stream

### POST /conversations/generate-title

**Mô tả:** Tự động sinh tiêu đề cho conversation

**Request Body:**
```json
{
  "conversation_id": "uuid",
  "first_question": "Không đội mũ bảo hiểm bị phạt bao nhiêu?"
}
```

**Response:**
```json
{
  "title": "Hỏi về mức phạt không đội mũ bảo hiểm",
  "generated_at": "2024-04-02T13:00:00Z"
}
```

### DELETE /conversations/{id}/checkpoints

**Mô tả:** Xóa LangGraph checkpoints (clear memory)

**Response:**
```json
{
  "success": true,
  "deleted_count": 5
}
```

### GET /law-detail/{node_id}

**Mô tả:** Lấy chi tiết node từ Neo4j

**Response:**
```json
{
  "id": "article_123",
  "type": "Article",
  "content": "Điều 5. Không đội mũ bảo hiểm...",
  "related_penalties": [
    {
      "amount": "400.000 - 600.000 VNĐ",
      "description": "..."
    }
  ]
}
```

### GET /health

**Response:**
```json
{
  "status": "healthy",
  "services": {
    "neo4j": "connected",
    "redis": "connected",
    "postgres": "connected"
  },
  "uptime": 12345.67
}
```

### GET /debug

**Response:**
```json
{
  "config": {
    "neo4j_uri": "bolt://localhost:7687",
    "redis_url": "redis://localhost:6379",
    "embed_model": "sentence-transformers/nli-mpnet-base-v2"
  },
  "cache_stats": {
    "hit_rate": 0.35,
    "total_queries": 1500,
    "cache_hits": 525
  },
  "neo4j_stats": {
    "node_count": 5234,
    "relationship_count": 8901
  }
}
```

### DELETE /cache

**Mô tả:** Flush toàn bộ semantic cache

**Response:**
```json
{
  "success": true,
  "cleared_keys": 342
}
```

---

## ⚙️ Configuration

### Environment Variables

```env
# Neo4j Knowledge Graph
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password

# PostgreSQL (LangGraph Checkpoints)
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/chatbot_law

# Redis Stack (Semantic Cache)
REDIS_URL=redis://localhost:6379

# Google Gemini LLM
GOOGLE_API_KEY=your_api_key

# Web Search
SERPER_API_KEY=your_serper_key
FIRECRAWL_API_KEY=your_firecrawl_key

# Internal Auth
X_INTERNAL_SECRET=random_secret_string

# Server Config
FASTAPI_URI=127.0.0.1
FASTAPI_PORT=8001

# Embedding Model
EMBED_MODEL_ID=sentence-transformers/nli-mpnet-base-v2

# Optional: LangSmith Tracing
LANGCHAIN_TRACING_V2=false
LANGCHAIN_API_KEY=
```

### Pydantic Settings (config.py)

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Neo4j
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    
    # PostgreSQL
    database_url: str
    
    # Redis
    redis_url: str
    
    # LLM
    google_api_key: str
    embed_model_id: str = "sentence-transformers/nli-mpnet-base-v2"
    
    # Web Search
    serper_api_key: str
    firecrawl_api_key: str
    
    # Server
    fastapi_uri: str = "127.0.0.1"
    fastapi_port: int = 8001
    x_internal_secret: str
    
    # Optional
    langchain_tracing_v2: bool = False
    langchain_api_key: str | None = None
    
    class Config:
        env_file = "../.env"  # Load from root .env
        case_sensitive = False
```

---

## 🧪 Testing & Evaluation

### RAGAS Evaluation

```python
from app.eval.service import evaluate_response

# Test a response
result = await evaluate_response(
    question="Không đội mũ bảo hiểm bị phạt bao nhiêu?",
    answer="Theo Nghị định 168/2024, mức phạt...",
    retrieved_docs=[...],
    ground_truth="400.000 - 600.000 VNĐ"
)

print(result)
# {
#   "faithfulness": 0.95,      # Độ trung thực với nguồn
#   "answer_relevancy": 0.92,  # Độ liên quan với câu hỏi
#   "context_recall": 0.88,    # Retrieved docs có đủ không
#   "context_precision": 0.91  # Retrieved docs có chính xác không
# }
```

### Unit Tests

```bash
cd ai-service
pytest test/ -v
```

---

## 🔧 Troubleshooting

### Neo4j Connection Failed

```bash
# Check Neo4j is running
docker ps | grep neo4j

# Test connection
python -c "from neo4j import GraphDatabase; driver = GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', 'password')); driver.verify_connectivity(); print('OK')"
```

### Redis RediSearch not available

```bash
# Must use Redis Stack, not standard Redis
docker run -d --name redis-stack -p 6379:6379 redis/redis-stack:latest

# Verify RediSearch module
redis-cli
> MODULE LIST
# Should show "search"
```

### PostgreSQL AsyncPostgresSaver Failed

```bash
# Check DATABASE_URL format
# Correct: postgresql+psycopg://user:password@host:5432/dbname
# Wrong: postgresql://user:password@host:5432/dbname (missing +psycopg)

# Test connection
python -c "import asyncio; from psycopg_pool import AsyncConnectionPool; asyncio.run(AsyncConnectionPool('your_url').open())"
```

### LLM API Rate Limit

```python
# Adjust retry config in rag_service.py
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash-preview",
    temperature=0.1,
    max_retries=3,
    timeout=30.0
)
```

### Slow Response Time

1. **Check cache hit rate:**
```bash
curl http://localhost:8001/cache/stats
# Target hit rate: >30%
```

2. **Enable parallel retrieval:**
```python
# Already enabled in graph_retrieval.py
results = await asyncio.gather(
    vector_search(),
    keyword_search(),
    graph_traversal(),
    consequence_search()
)
```

3. **Reduce thinking budget:**
```python
# In router_node(), adjust complexity_level logic
if simple_question:
    complexity_level = 1  # No thinking budget
```

---

## 📈 Performance Metrics

### Typical Latency (with cache miss)

| Component | Latency | Percentage |
|-----------|---------|------------|
| Router | 200ms | 10% |
| 4-Prong Retrieval | 400ms | 20% |
| LLM Reasoning | 1200ms | 60% |
| Reflection | 150ms | 7.5% |
| Synthesis | 50ms | 2.5% |
| **Total** | **~2000ms** | **100%** |

### With Cache Hit

| Component | Latency |
|-----------|---------|
| Cache Lookup | 10ms |
| **Total** | **~10ms** |

### Token Usage (per query)

- Input tokens: 150-300 (context + question)
- Output tokens: 200-500 (answer)
- Thinking tokens: 0-4096 (depends on complexity)
- Total: 350-4896 tokens
- Cost: $0.001 - $0.005 USD per query (Gemini pricing)

---

## 🎯 Best Practices

1. **Always use async/await** cho I/O operations
2. **Enable semantic caching** cho production (hit rate ~30-40%)
3. **Monitor LangSmith traces** khi debug (set `LANGCHAIN_TRACING_V2=true`)
4. **Set thinking budget** based on query complexity
5. **Use RRF k=60** cho optimal ranking
6. **Implement circuit breaker** cho external APIs
7. **Log all LLM calls** với token usage
8. **Version control prompts** (YAML files in git)

---

## 📚 Tài liệu tham khảo

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Neo4j Vector Search](https://neo4j.com/docs/vector-search/)
- [Redis RediSearch](https://redis.io/docs/stack/search/)
- [Gemini API](https://ai.google.dev/docs)
- [RAGAS Evaluation](https://docs.ragas.io/)

---

**Cập nhật:** 2024-04-02  
**Tác giả:** AI Service Team
