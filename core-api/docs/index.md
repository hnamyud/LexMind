# Core API reference

Core API is the primary FastAPI service at port `8080`. It keeps compatibility routes such as `/auth/login` and provides `/api/v1` aliases for public endpoints.

| Area | Document |
| --- | --- |
| Authentication | `auth.md` |
| Conversations | `conversations.md` |
| Messages | `messages.md` |
| Chat | `chat.md` |
| Feedback | `feedbacks.md` |
| Administration | `admin.md` |
| Evaluation | `eval-api.md` |

Use `GET /healthz` for service readiness. The `frontend-cursor-pagination.md` document describes cursor pagination for conversation and message history.
