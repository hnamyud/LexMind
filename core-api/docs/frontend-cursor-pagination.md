# Hướng dẫn Frontend: Cursor Pagination

FastAPI core hỗ trợ cursor pagination cho lịch sử conversation và message. Dùng các endpoint này cho infinite scroll/lazy loading; không dùng `current` hoặc `pageSize` cùng lúc với cursor.

| Dữ liệu | Endpoint | Sắp xếp |
|---|---|---|
| Conversations | `GET /conversations/cursor` | `updatedAt DESC, id DESC` |
| Messages | `GET /messages/cursor` | `createdAt DESC, id DESC` |

Cả hai endpoint cũng có alias `/api/v1/...`. Frontend nên chọn một base URL duy nhất, ví dụ `http://localhost:8080/api/v1` khi chạy Core API.

## Contract chung

Request đầu tiên không truyền `cursor`:

```http
GET /conversations/cursor?limit=20
Authorization: Bearer <access-token>
```

Response thành công luôn có envelope:

```ts
type CursorPage<T> = {
  statusCode: 200;
  message: string;
  data: {
    result: T[];
    pageInfo: {
      nextCursor: string | null;
      hasMore: boolean;
    };
  };
};
```

- `nextCursor` là opaque token: chỉ lưu và gửi lại nguyên văn, không tự decode/chỉnh sửa.
- Khi `hasMore` là `false`, dừng gọi tiếp; `nextCursor` sẽ là `null`.
- Cursor không hợp lệ trả `400`.
- Gửi JWT qua `Authorization: Bearer <access-token>`.

## Conversations sidebar

```ts
type Conversation = {
  id: string;
  title: string | null;
  summary: string | null;
  createdAt: string;
  updatedAt: string;
};

async function getConversationPage(cursor?: string | null) {
  const params = new URLSearchParams({ limit: "20" });
  if (cursor) params.set("cursor", cursor);

  const response = await api.get<CursorPage<Conversation>>(
    `/conversations/cursor?${params}`,
  );
  return response.data.data;
}
```

Khi tải thêm, nối kết quả vào cuối danh sách vì API trả conversations mới nhất trước:

```ts
const page = await getConversationPage(nextCursor);
setConversations((previous) => [...previous, ...page.result]);
setNextCursor(page.pageInfo.nextCursor);
setHasMore(page.pageInfo.hasMore);
```

Sau khi user gửi message mới, conversation đó có `updatedAt` mới và quay lên đầu. Reset sidebar rồi gọi lại trang đầu thay vì cố ghép lại với cursor cũ:

```ts
setConversations([]);
setNextCursor(null);
setHasMore(true);
const firstPage = await getConversationPage();
setConversations(firstPage.result);
setNextCursor(firstPage.pageInfo.nextCursor);
setHasMore(firstPage.pageInfo.hasMore);
```

## Chat history: tải message cũ hơn

```ts
type ChatMessage = {
  id: string;
  sender: "user" | "bot";
  content: string;
  thought: string | null;
  metadata: Record<string, unknown> | null;
  createdAt: string;
};

async function getMessagePage(conversationId: string, cursor?: string | null) {
  const params = new URLSearchParams({ conversationId, limit: "30" });
  if (cursor) params.set("cursor", cursor);

  const response = await api.get<CursorPage<ChatMessage>>(
    `/messages/cursor?${params}`,
  );
  return response.data.data;
}
```

API trả newest-first. Với chat UI hiển thị oldest-first, đảo `result` trước khi render/chèn:

```ts
const page = await getMessagePage(conversationId, nextCursor);
const olderMessages = [...page.result].reverse();

// Khi user scroll lên đầu, prepend message cũ hơn.
setMessages((current) => [...olderMessages, ...current]);
setNextCursor(page.pageInfo.nextCursor);
setHasMore(page.pageInfo.hasMore);
```

Khi mở conversation lần đầu, frontend cũng nên đảo trang đầu trước khi gán vào state:

```ts
const firstPage = await getMessagePage(conversationId);
setMessages([...firstPage.result].reverse());
```

## React hook tối giản

```tsx
function useCursorMessages(conversationId: string | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);

  const loadOlder = useCallback(async () => {
    if (!conversationId || loading || !hasMore) return;
    setLoading(true);
    try {
      const page = await getMessagePage(conversationId, nextCursor);
      setMessages((current) => [...page.result.reverse(), ...current]);
      setNextCursor(page.pageInfo.nextCursor);
      setHasMore(page.pageInfo.hasMore);
    } finally {
      setLoading(false);
    }
  }, [conversationId, hasMore, loading, nextCursor]);

  useEffect(() => {
    setMessages([]);
    setNextCursor(null);
    setHasMore(true);
  }, [conversationId]);

  return { messages, hasMore, loading, loadOlder };
}
```

Thực tế nên gọi `loadOlder()` riêng sau khi reset state hoặc dùng `AbortController` để huỷ request của conversation cũ khi user chuyển chat nhanh.

## Migration từ page/offset cũ

Endpoint cũ vẫn hoạt động:

```text
GET /conversations?current=1&pageSize=20
GET /messages?conversationId=<uuid>&current=1&pageSize=30
```

Không trộn response offset với cursor trong cùng state. Chuyển từng màn hình:

1. Sidebar conversations dùng `/conversations/cursor`.
2. Chat history dùng `/messages/cursor`.
3. Bỏ logic tính `pages`, `total` và nút nhảy đến số trang ở hai màn hình này.
4. Giữ cursor của riêng từng conversation; reset khi `conversationId` đổi.

## Xử lý lỗi

- `401`: access token hết hạn; chạy flow refresh token hiện có rồi retry một lần.
- `403`/`401` khi messages: user không sở hữu conversation hoặc token không hợp lệ.
- `400`: bỏ cursor đang lưu, reset danh sách và tải trang đầu.
- Không gọi đồng thời nhiều lần `loadOlder`; khoá bằng `loading` để tránh duplicate message.
