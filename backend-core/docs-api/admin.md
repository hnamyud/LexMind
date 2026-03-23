# Admin API

Đường dẫn cơ sở: `/admin`

Module này cung cấp các endpoint dành riêng cho quản trị viên (Admin) để giám sát hệ thống, quản lý người dùng, hội thoại và theo dõi hiệu suất/chất lượng AI.

**Yêu cầu quyền hạn**: Tất cả endpoints đều yêu cầu quyền Admin (`Action.Manage, 'all'`).

---

## 1. System Monitoring (Phase 3) 🚀

Các API giám sát sức khỏe và thống kê tổng quan hệ thống.

| Endpoint | Method | Mô tả | Query Params |
|----------|--------|-------|--------------|
| `/health` | `GET` | Kiểm tra sức khỏe (Health Check) của các service: Database, AI Service, Redis. | - |
| `/system/stats` | `GET` | Thống kê tổng quan: Users, Request rate, Error rate, Response times. | - |

**Ví dụ phản hồi check health:**
```json
{
  "status": "healthy",
  "timestamp": "2026-03-22T10:00:00Z",
  "services": {
    "database": { "status": "up", "responseTime": 12 },
    "aiService": { "status": "up", "responseTime": 45 },
    "redis": { "status": "up", "responseTime": 5 }
  }
}
```

**Ví dụ phản hồi System Stats (`GET /admin/system/stats`):**
```json
{
  "activeUsers": {
    "last24h": 450,
    "last7d": 1200,
    "last30d": 3500
  },
  "requestRate": {
    "messagesLast24h": 1500,
    "messagesLast7d": 8500,
    "avgMessagesPerDay": 285
  },
  "errorRate": {
    "last24h": {
      "total": 12,
      "percentage": 0.8
    },
    "last7d": {
      "total": 45,
      "percentage": 1.2
    }
  },
  "performance": {
    "avgResponseTime": 2350,
    "slowRequests24h": 45,
    "slowRequestsPercentage": 3.2
  }
}
```

---

## 2. Feedback Management (Phase 3) 🚀

API quản lý và phân tích phản hồi từ người dùng về chất lượng câu trả lời AI.

| Endpoint | Method | Mô tả | Query Params chính |
|----------|--------|-------|--------------------|
| `/feedbacks` | `GET` | Lấy danh sách feedbacks (có pagination và filter). | `page`, `limit`, `isLike` (bool), `userId`, `conversationId`, `search` (reason), `dateFrom`, `dateTo`, `sortBy`, `order` |
| `/feedbacks/analytics` | `GET` | Phân tích feedback: trends, tỷ lệ like/dislike, top reasons, correlation với response time. | `dateFrom`, `dateTo` |

**Ví dụ phản hồi Feedbacks (`GET /admin/feedbacks`):**
```json
{
  "data": [
    {
      "id": "uuid",
      "messageId": "uuid",
      "userId": "uuid",
      "user": { "id": "uuid", "fullName": "Nguyen Van A", "email": "a@example.com" },
      "message": {
        "content": "Bot trả lời sai",
        "question": "Quy định về thuế TNCN?",
        "conversation": { "id": "uuid", "title": "Thuế cá nhân" },
        "aiMetrics": { "responseTime": 1500, "model": "gemini-3-flash-preview" }
      },
      "isLike": false,
      "reason": "Sai thông tin",
      "createdAt": "2026-03-22T14:30:00Z"
    }
  ],
  "total": 50,
  "stats": {
    "totalLikes": 40,
    "totalDislikes": 10,
    "likeRatio": 0.8
  }
}
```

**Ví dụ phản hồi Analytics (`GET /admin/feedbacks/analytics`):**
```json
{
  "overview": {
    "totalFeedbacks": 100,
    "feedbackRate": 0.25,
    "likeCount": 80,
    "dislikeCount": 20,
    "likeRatio": 0.8,
    "qualityScore": 80
  },
  "dislikeReasons": [
    { "reason": "Sai thông tin", "count": 10 },
    { "reason": "Không liên quan", "count": 5 }
  ],
  "feedbackByResponseTime": [
    {
       "responseTimeRange": "0-1000ms",
       "totalMessages": 50,
       "likeRatio": 0.95
    }
  ]
}
```


---

## 3. AI Performance & Errors

Theo dõi hiệu suất kỹ thuật và các lỗi phát sinh từ AI Service.

| Endpoint | Method | Mô tả | Query Params chính |
|----------|--------|-------|--------------------|
| `/ai/performance` | `GET` | Metrics về tốc độ, tokens, chi phí. | `dateFrom`, `dateTo`, `groupBy` (hour, day, week...) |
| `/ai/quality` | `GET` | Metrics về chất lượng dựa trên feedback. | `dateFrom`, `dateTo`, `groupBy` |
| `/ai/cache` | `GET` | Tình trạng Semantic Cache: hit rate, tiết kiệm thời gian, so sánh response time. | `dateFrom`, `dateTo` |
| `/ai/errors` | `GET` | Danh sách lỗi AI (timeout, neo4j error...) để debugging. | `page`, `limit`, `errorCode`, `dateFrom`... |

**Ví dụ phản hồi Performance (`GET /admin/ai/performance`):**
```json
{
  "overview": {
    "avgResponseTime": 1500,
    "p50ResponseTime": 1200,
    "p95ResponseTime": 3500,
    "p99ResponseTime": 5000,
    "avgTTFT": 400,
    "totalCost": 5.20,
    "avgCostPerMessage": 0.005
  },
  "modelDistribution": [
    { "model": "gemini-3-flash-preview", "count": 1000, "avgTime": 1200 },
    { "model": "gpt-4o", "count": 200, "avgTime": 2500 }
  ],
  "tokenUsage": {
    "totalInputTokens": 100000,
    "totalOutputTokens": 200000,
    "avgInputTokensPerMessage": 80
  }
}
```

**Ví dụ phản hồi Cache Analytics (`GET /admin/ai/cache`):**
```json
{
  "overview": {
    "totalQueries": 1250,
    "cacheHits": 312,
    "cacheMisses": 938,
    "hitRatePercent": 24.96,
    "avgTimeSavedMs": 4200,
    "totalTimeSavedMs": 1310400
  },
  "responseTimeComparison": {
    "cached": { "avg": 850, "p50": 720, "p95": 1400 },
    "nonCached": { "avg": 5050, "p50": 4600, "p95": 8200 }
  },
  "timeSeries": [
    { "date": "2026-03-22", "hits": 45, "misses": 120, "hitRate": 0.27 },
    { "date": "2026-03-23", "hits": 67, "misses": 98, "hitRate": 0.41 }
  ]
}
```

**Ví dụ phản hồi Errors (`GET /admin/ai/errors`):**
```json
{
  "data": [
    {
       "messageId": "uuid",
       "errorType": "AI_SERVICE_TIMEOUT",
       "errorMessage": "Request timed out after 30000ms",
       "question": "Thuế suất GTGT?",
       "timestamp": "2026-03-22T10:00:00Z",
       "metadata": { "model": "gemini-3-flash-preview", "retryCount": 1 }
    }
  ],
  "total": 5,
  "errorsByType": [
     { "type": "AI_SERVICE_TIMEOUT", "count": 3 },
     { "type": "NEO4J_CONNECTION_ERROR", "count": 2 }
  ]
}
```


---

## 4. User Management

| Endpoint | Method | Mô tả | Query Params chính |
|----------|--------|-------|--------------------|
| `/users` | `GET` | Danh sách người dùng hệ thống. | `page`, `limit`, `role` (USER, ADMIN), `search` (email/name), `sortBy`, `order` |
| `/users/:userId` | `GET` | Chi tiết người dùng và hoạt động gần đây. | - |

**Ví dụ phản hồi Users (`GET /admin/users`):**
```json
{
  "data": [
    {
      "id": "uuid",
      "email": "user@example.com",
      "fullName": "Le Van User",
      "role": "USER",
      "createdAt": "2026-03-01T00:00:00Z",
      "stats": {
        "conversationCount": 15,
        "feedbackCount": 3,
        "lastActiveAt": "2026-03-22T08:00:00Z"
      }
    }
  ],
  "total": 100,
  "page": 1,
  "limit": 20
}
```

**Ví dụ phản hồi User Detail (`GET /admin/users/:userId`):**
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "fullName": "Le Van User",
  "role": "USER",
  "stats": {
    "totalConversations": 15,
    "totalFeedbacks": 3,
    "likeFeedbacks": 2,
    "dislikeFeedbacks": 1,
    "avgMessagesPerConversation": 8,
    "lastActiveAt": "2026-03-22T08:00:00Z"
  },
  "recentConversations": [
    {
      "id": "uuid",
      "title": "Hỏi về luật hình sự",
      "messageCount": 10,
      "createdAt": "2026-03-22T07:00:00Z"
    }
  ]
}
```


---

## 5. Conversation Management

| Endpoint | Method | Mô tả | Query Params chính |
|----------|--------|-------|--------------------|
| `/conversations` | `GET` | Duyệt tất cả hội thoại của người dùng. | `page`, `limit`, `userId`, `dateFrom`, `dateTo`, `hasNegativeFeedback` (lọc hội thoại bị dislike) |
| `/conversations/stats` | `GET` | Thống kê lượng hội thoại theo thời gian. | `dateFrom`, `dateTo`, `groupBy` |
| `/conversations/:id` | `GET` | Xem chi tiết nội dung hội thoại (gồm messages). | - |

**Ví dụ phản hồi Conversations (`GET /admin/conversations`):**
```json
{
  "data": [
    {
      "id": "uuid",
      "title": "Hỏi về luật hình sự",
      "userId": "uuid",
      "user": { "fullName": "Nguyễn Văn A" },
      "messageCount": 10,
      "avgResponseTime": 1500,
      "hasNegativeFeedback": true,
      "createdAt": "2026-03-22T07:00:00Z"
    }
  ],
  "total": 500,
  "page": 1,
  "limit": 20
}
```

**Ví dụ phản hồi Conversation Detail (`GET /admin/conversations/:id`):**
```json
{
  "id": "uuid",
  "title": "Hỏi về luật hình sự",
  "userId": "uuid",
  "user": { "id": "uuid", "email": "a@example.com" },
  "messages": [
    {
      "id": "msg1",
      "sender": "user",
      "content": "Tuổi chịu trách nhiệm hình sự là bao nhiêu?",
      "createdAt": "2026-03-22T07:05:00Z"
    },
    {
      "id": "msg2",
      "sender": "bot",
      "content": "Theo Điều 12 Bộ luật hình sự...",
      "aiMetrics": { "totalTime": 1200, "cost": 0.0005 },
      "feedback": {
        "isLike": true,
        "reason": null
      }
    }
  ],
  "stats": {
    "totalMessages": 2,
    "avgResponseTime": 1200,
    "totalCost": 0.0005,
    "feedbackCount": 1,
    "likeFeedbacks": 1,
    "dislikeFeedbacks": 0
  }
}
```


---

## Data Objects (DTOs)

### StatsQueryDto
Sử dụng chung cho các API thống kê (`/stats`, `/analytics`, `/performance`).
- `dateFrom`: ISO 8601 string
- `dateTo`: ISO 8601 string
- `groupBy`: 'hour' | 'day' | 'week' | 'month'

### GetFeedbacksDto
- `isLike`: boolean (true: Like, false: Dislike)
- `search`: string (tìm kiếm trong lý do dislike)
