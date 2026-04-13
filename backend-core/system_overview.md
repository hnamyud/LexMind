# Backend Core - NestJS API Gateway 

Backend Core là API Gateway của hệ thống Chatbot Luật, xử lý **authentication**, **authorization**, **conversation management**, và **streaming proxy** tới AI Service.

## 📑 Mục lục

- [Tính năng chính](#-tính-năng-chính)
- [Kiến trúc tổng quan](#️-kiến-trúc-tổng-quan)
- [Tech Stack](#️-tech-stack)
- [Cấu trúc thư mục](#-cấu-trúc-thư-mục)
- [Authentication & Authorization](#-authentication--authorization)
- [Chat & Streaming](#-chat--streaming)
- [Database Schema](#-database-schema)
- [Event-Driven Architecture](#-event-driven-architecture)
- [Rate Limiting](#-rate-limiting)
- [API Endpoints](#-api-endpoints)
- [Configuration](#️-configuration)
- [Testing](#-testing)
- [Troubleshooting](#-troubleshooting)

---

## Tính năng chính

### Authentication & Authorization

- **JWT Authentication**: Access token + Refresh token
- **Google OAuth 2.0**: Social login
- **OTP Verification**: Email-based OTP for password reset
- **CASL Authorization**: Policy-based access control
- **Password Hashing**: bcryptjs with salt rounds

### Conversation Management

- **CRUD Operations**: Create, Read, Update, Delete conversations
- **Soft Delete**: Conversations can be restored
- **Auto-Title Generation**: Event-driven background task
- **Message History**: Full conversation context
- **Feedback System**: Like/dislike with optional reason

### Event-Driven Architecture

- **Event Emitter**: `@nestjs/event-emitter` for async tasks
- **Fire-and-Forget**: Non-blocking background jobs
- **Title Generation**: Auto-generate conversation titles
- **Extensible**: Easy to add new event listeners

### Security & Performance

- **Rate Limiting**: Multi-tier throttling (short/medium/long)
- **Helmet**: Security headers
- **CORS**: Configurable origins
- **Compression**: gzip response compression
- **Caching**: Redis for sessions and rate limits
- **Streaming**: Server-Sent Events (SSE) for real-time responses

### Metrics & Analytics

- **AI Metrics**: Token usage, latency, cost per message
- **User Feedback**: Track satisfaction rates
- **Admin Dashboard**: System analytics and user management

---

## Kiến trúc tổng quan

```text
┌────────────────────────────────────────────────────────────┐
│                   NestJS Application                       │
│                      (Port 8080)                           │
└────────────┬───────────────────────────────────────────────┘
             │
             ├─── Guards Layer (JWT, Policy, Throttle)
             │
             ├─── Controllers Layer (REST API Endpoints)
             │    ├── AuthController
             │    ├── ChatController
             │    ├── ConversationsController
             │    ├── MessagesController
             │    ├── FeedbacksController
             │    ├── UsersController
             │    └── AdminController
             │
             ├─── Services Layer (Business Logic)
             │    ├── AuthService
             │    ├── ChatService
             │    │    └── TitleGeneratorService (Event Listener)
             │    ├── ConversationsService
             │    ├── MessagesService
             │    ├── FeedbacksService
             │    └── UsersService
             │
             ├─── Core Layer (Cross-cutting)
             │    ├── CASL (Authorization policies)
             │    ├── Decorators (@GetUser, @ResponseMessage)
             │    ├── Interceptors (Transform response)
             │    └── Middleware (Logger)
             │
             ├─── Shared Layer (Utilities)
             │    ├── PrismaService (ORM)
             │    ├── RedisModule (Cache)
             │    └── MailerModule (Email)
             │
             └─── External Dependencies
                  ├── PostgreSQL (Business data)
                  ├── Redis (Cache, sessions)
                  └── FastAPI AI Service (HTTP proxy)
```

### Request Flow (Chat Stream)

```text
┌─────────┐                                         ┌──────────┐
│ Client  │───1. POST /chat/ask/stream─────────────▶│ NestJS   │
│         │   (JWT in Authorization header)         │          │
└─────────┘                                         └────┬─────┘
     ▲                                                   │
     │                                                   │
     │                                              2. Guards:
     │                                                 - JWT Auth ✓
     │                                                 - Rate Limit ✓
     │                                                 - Policy ✓
     │                                                   │
     │                                                   ▼
     │                                           3. ChatController
     │                                              @Post('ask/stream')
     │                                                   │
     │                                                   ▼
     │                                           4. ChatService.askAI()
     │                                              - Save user message
     │                                              - Proxy to FastAPI
     │                                                   │
     │                                                   ▼
     │                                           ┌──────────────┐
     │                                           │  FastAPI     │
     │                                           │  AI Service  │
     │                                           └──────┬───────┘
     │                                                  │
     │                                                  │ RAG Pipeline
     │                                                  │ (NDJSON stream)
     │                                                  │
     │        5. Transform NDJSON → SSE                │
     │           and stream to client                  │
     │◀────────────────────────────────────────────────┘
     │
     │        6. On stream complete:
     │           - Save bot message
     │           - Emit CONVERSATION_TITLE_EVENT
     │           - Return to client
     │
     │        7. Event Listener (async):
     │           - TitleGeneratorService
     │           - Call FastAPI /generate-title
     │           - Update conversation.title
```

---

## Tech Stack

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Framework** | NestJS | 11.0.1 | Progressive Node.js framework |
| **ORM** | Prisma | 7.4.2 | Type-safe database ORM |
| **Database** | PostgreSQL | 16+ | Primary data store |
| **Cache** | Redis (ioredis) | 5.10.0 | Sessions, rate limiting |
| **Authentication** | Passport | 0.7.0 | Auth strategies |
| **JWT** | @nestjs/jwt | 11.0.0 | Token generation/validation |
| **OAuth** | passport-google-oauth20 | 2.0.0 | Google SSO |
| **Authorization** | CASL | 6.7.3 | Policy-based access control |
| **Event Bus** | @nestjs/event-emitter | 3.0.0 | Event-driven architecture |
| **Rate Limiting** | @nestjs/throttler | 6.5.0 | Request throttling |
| **Security** | Helmet | 8.1.0 | HTTP security headers |
| **Password Hash** | bcryptjs | 2.4.3 | Password encryption |
| **Email** | nodemailer | 6.9.16 | Email sending |
| **Validation** | class-validator | 0.14.1 | DTO validation |
| **HTTP Client** | axios | 1.13.6 | External API calls |
| **API Docs** | @nestjs/swagger | 11.0.0 | OpenAPI documentation |

---

## Cấu trúc thư mục

```text
backend-core/
├── prisma/
│   ├── schema.prisma              # Database schema definition
│   ├── migrations/                # Version-controlled migrations
│   │   └── 20240101_initial/
│   └── seed.ts                    # Database seeding script
│
├── src/
│   ├── main.ts                    # Application entry point
│   ├── app.module.ts              # Root module
│   ├── app.controller.ts          # Health check endpoint
│   ├── app.service.ts             # App-level services
│   │
│   ├── common/                    # Shared types and enums
│   │   ├── enum/
│   │   │   ├── role.enum.ts       # USER, ADMIN
│   │   │   └── action.enum.ts     # CREATE, READ, UPDATE, DELETE
│   │   ├── guards/
│   │   │   ├── jwt-auth.guard.ts  # JWT authentication
│   │   │   ├── policy.guard.ts    # CASL authorization
│   │   │   └── throttler.guard.ts # Rate limiting
│   │   └── interfaces/
│   │       ├── user.interface.ts  # IUser type
│   │       └── request.interface.ts # Extended Request
│   │
│   ├── config/                    # Configuration modules
│   │   ├── helmet.config.ts       # Security headers
│   │   └── mail.config.ts         # Mailer configuration
│   │
│   ├── core/                      # Core functionalities
│   │   ├── casl/
│   │   │   ├── casl-ability.factory.ts # Define abilities
│   │   │   └── casl.module.ts
│   │   ├── decorators/
│   │   │   ├── get-user.decorator.ts   # @GetUser()
│   │   │   ├── response-message.decorator.ts # @ResponseMessage()
│   │   │   └── check-policies.decorator.ts   # @CheckPolicies()
│   │   ├── interceptors/
│   │   │   └── transform.interceptor.ts # Standardize response
│   │   └── middleware/
│   │       └── logger.middleware.ts     # Request logging
│   │
│   ├── modules/
│   │   ├── auth/
│   │   │   ├── auth.controller.ts
│   │   │   ├── auth.service.ts
│   │   │   ├── auth.module.ts
│   │   │   ├── dto/
│   │   │   │   ├── register-user.dto.ts
│   │   │   │   ├── login.dto.ts
│   │   │   │   ├── refresh-token.dto.ts
│   │   │   │   └── change-password.dto.ts
│   │   │   └── passport/
│   │   │       ├── jwt.strategy.ts      # JWT validation
│   │   │       ├── local.strategy.ts    # Email/password
│   │   │       └── google.strategy.ts   # Google OAuth
│   │   │
│   │   ├── chat/
│   │   │   ├── chat.controller.ts
│   │   │   ├── chat.service.ts
│   │   │   ├── title-generator.service.ts # Event listener
│   │   │   ├── chat.module.ts
│   │   │   ├── events/
│   │   │   │   └── conversation-title.event.ts
│   │   │   └── dto/
│   │   │       └── question.dto.ts
│   │   │
│   │   ├── conversations/
│   │   │   ├── conversations.controller.ts
│   │   │   ├── conversations.service.ts
│   │   │   ├── conversations.module.ts
│   │   │   └── dto/
│   │   │       ├── create-conversation.dto.ts
│   │   │       └── update-conversation.dto.ts
│   │   │
│   │   ├── messages/
│   │   │   ├── messages.controller.ts
│   │   │   ├── messages.service.ts
│   │   │   ├── messages.module.ts
│   │   │   └── dto/
│   │   │       ├── create-message.dto.ts
│   │   │       └── query-messages.dto.ts
│   │   │
│   │   ├── feedbacks/
│   │   │   ├── feedbacks.controller.ts
│   │   │   ├── feedbacks.service.ts
│   │   │   ├── feedbacks.module.ts
│   │   │   └── dto/
│   │   │       └── create-feedback.dto.ts
│   │   │
│   │   ├── users/
│   │   │   ├── users.controller.ts
│   │   │   ├── users.service.ts
│   │   │   ├── users.module.ts
│   │   │   └── dto/
│   │   │       └── update-user.dto.ts
│   │   │
│   │   ├── admin/
│   │   │   ├── admin.controller.ts
│   │   │   ├── admin.service.ts
│   │   │   └── admin.module.ts
│   │   │
│   │   └── eval/
│   │       ├── eval.controller.ts
│   │       └── eval.service.ts
│   │
│   └── shared/                    # Shared services
│       ├── prisma/
│       │   ├── prisma.service.ts  # Prisma client
│       │   └── prisma.module.ts
│       ├── cache/
│       │   ├── redis.service.ts   # Redis client
│       │   └── redis.module.ts
│       └── mailer/
│           ├── mailer.service.ts  # Email service
│           └── mailer.module.ts
│
├── test/                          # E2E tests
│   ├── app.e2e-spec.ts
│   └── jest-e2e.json
│
├── package.json
├── tsconfig.json
├── nest-cli.json
└── .env                           # Environment variables
```

---

## Authentication & Authorization

### JWT Strategy

**Access Token:** Short-lived (1 day)  
**Refresh Token:** Long-lived (15 days)

```typescript
// jwt.strategy.ts
@Injectable()
export class JwtStrategy extends PassportStrategy(Strategy) {
  constructor(
    private configService: ConfigService,
    private usersService: UsersService,
  ) {
    super({
      jwtFromRequest: ExtractJwt.fromAuthHeaderAsBearerToken(),
      secretOrKey: configService.get('JWT_ACCESS_SECRET'),
    });
  }

  async validate(payload: JwtPayload): Promise<IUser> {
    const user = await this.usersService.findById(payload.sub);
    if (!user) {
      throw new UnauthorizedException('User not found');
    }
    return user;
  }
}
```

### Google OAuth Strategy

```typescript
// google.strategy.ts
@Injectable()
export class GoogleStrategy extends PassportStrategy(Strategy, 'google') {
  constructor(
    configService: ConfigService,
    private authService: AuthService,
  ) {
    super({
      clientID: configService.get('GOOGLE_CLIENT_ID'),
      clientSecret: configService.get('GOOGLE_CLIENT_SECRET'),
      callbackURL: configService.get('GOOGLE_REDIRECT_URI'),
      scope: ['email', 'profile'],
    });
  }

  async validate(
    accessToken: string,
    refreshToken: string,
    profile: any,
  ): Promise<any> {
    const { id, emails, displayName } = profile;
    
    // Find or create user
    const user = await this.authService.validateOAuthUser({
      providerId: id,
      email: emails[0].value,
      fullName: displayName,
    });
    
    return user;
  }
}
```

### CASL Authorization

```typescript
// casl-ability.factory.ts
@Injectable()
export class CaslAbilityFactory {
  createForUser(user: IUser) {
    const { can, cannot, build } = new AbilityBuilder(
      createMongoAbility as CreateAbility<AppAbility>,
    );

    if (user.role === Role.ADMIN) {
      can(Action.Manage, 'all'); // Admin can do everything
    } else {
      can(Action.Read, 'Conversation', { userId: user.id });
      can(Action.Update, 'Conversation', { userId: user.id });
      can(Action.Delete, 'Conversation', { userId: user.id });
      can(Action.Create, 'Message');
      can(Action.Read, 'Message', { 'conversation.userId': user.id });
    }

    return build();
  }
}
```

**Sử dụng trong Controller:**

```typescript
@Controller('conversations')
@UseGuards(JwtAuthGuard, PoliciesGuard)
export class ConversationsController {
  @Delete(':id')
  @CheckPolicies((ability: AppAbility) => 
    ability.can(Action.Delete, 'Conversation')
  )
  async delete(@Param('id') id: string, @GetUser() user: IUser) {
    return this.conversationsService.delete(id, user.id);
  }
}
```

### Password Management

```typescript
// auth.service.ts
import * as bcrypt from 'bcryptjs';

async hashPassword(password: string): Promise<string> {
  const salt = await bcrypt.genSalt(10);
  return bcrypt.hash(password, salt);
}

async comparePassword(password: string, hash: string): Promise<boolean> {
  return bcrypt.compare(password, hash);
}

async changePassword(userId: string, oldPassword: string, newPassword: string) {
  const user = await this.usersService.findById(userId);
  
  const isValid = await this.comparePassword(oldPassword, user.password);
  if (!isValid) {
    throw new BadRequestException('Old password is incorrect');
  }
  
  const hashedPassword = await this.hashPassword(newPassword);
  await this.usersService.update(userId, { password: hashedPassword });
}
```

---

## Chat & Streaming

### Streaming Proxy (NDJSON → SSE)

```typescript
// chat.service.ts
async askAI(
  question: string,
  conversationId: string,
  userId: string,
  res: Response,
) {
  // 1. Save user message
  const userMessage = await this.messagesService.create({
    conversationId,
    sender: 'user',
    content: question,
  });

  // 2. Proxy to FastAPI
  const response = await axios.post(
    `${FASTAPI_URL}/ask/stream`,
    {
      question,
      conversation_id: conversationId,
      message_id: userMessage.id,
      user_id: userId,
    },
    {
      headers: { 'INTERNAL-SECRET': X_INTERNAL_SECRET },
      responseType: 'stream',
    },
  );

  // 3. Transform NDJSON → SSE
  let botAnswer = '';
  let thought = '';
  let metadata = {};

  response.data.on('data', (chunk: Buffer) => {
    const lines = chunk.toString().split('\n').filter(Boolean);
    
    for (const line of lines) {
      const data = JSON.parse(line);
      
      if (data.type === 'thought') {
        thought += data.content;
        res.write(`data: ${JSON.stringify({ type: 'thought', content: data.content })}\n\n`);
      } else if (data.type === 'answer') {
        botAnswer += data.content;
        res.write(`data: ${JSON.stringify({ type: 'answer', content: data.content })}\n\n`);
      } else if (data.type === 'metadata') {
        metadata = data;
      } else if (data.type === 'done') {
        res.write(`data: ${JSON.stringify({ type: 'done' })}\n\n`);
        res.end();
      }
    }
  });

  response.data.on('end', async () => {
    // 4. Save bot message
    const botMessage = await this.messagesService.create({
      conversationId,
      sender: 'bot',
      content: botAnswer,
      thought,
      metadata,
    });

    // 5. Emit event for title generation (first message only)
    const messageCount = await this.messagesService.count(conversationId);
    if (messageCount === 2) { // user + bot = 2
      this.eventEmitter.emit(
        'conversation.title_needed',
        new ConversationTitleEvent(conversationId, question),
      );
    }
  });
}
```

### SSE Response Format

Client nhận được stream theo format:

```
data: {"type":"thought","content":"Đang phân tích câu hỏi..."}

data: {"type":"thought","content":"Tìm kiếm trong Knowledge Graph..."}

data: {"type":"answer","content":"Theo Nghị định 168/2024, "}

data: {"type":"answer","content":"mức phạt không đội mũ bảo hiểm là "}

data: {"type":"answer","content":"400.000 - 600.000 VNĐ."}

data: {"type":"metadata","sources":[{"url":"...","title":"..."}]}

data: {"type":"done"}
```

---

## Database Schema

### Prisma Schema

```prisma
// prisma/schema.prisma
datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}

generator client {
  provider = "prisma-client-js"
}

enum Role {
  USER
  ADMIN
}

enum Sender {
  user
  bot
}

model User {
  id            String         @id @default(uuid())
  email         String         @unique
  password      String?        // Nullable for OAuth users
  fullName      String?
  role          Role           @default(USER)
  createdAt     DateTime       @default(now())
  updatedAt     DateTime       @updatedAt
  deletedAt     DateTime?      // Soft delete
  
  conversations Conversation[]
  feedbacks     Feedback[]
  
  @@map("users")
}

model Conversation {
  id        String    @id @default(uuid())
  userId    String
  title     String?   // Auto-generated
  summary   String?
  createdAt DateTime  @default(now())
  updatedAt DateTime  @updatedAt
  isDeleted Boolean   @default(false)
  deletedAt DateTime?
  
  user      User      @relation(fields: [userId], references: [id])
  messages  Message[]
  
  @@index([userId, isDeleted])
  @@map("conversations")
}

model Message {
  id             String       @id @default(uuid())
  conversationId String
  sender         Sender
  content        String       @db.Text
  thought        String?      @db.Text  // LLM reasoning
  metadata       Json?        // Sources, citations
  parentId       String?      // For threading
  createdAt      DateTime     @default(now())
  
  conversation   Conversation @relation(fields: [conversationId], references: [id], onDelete: Cascade)
  aiMetrics      AIMetrics?
  feedbacks      Feedback[]
  
  @@index([conversationId, createdAt])
  @@map("messages")
}

model AIMetrics {
  id                String   @id @default(uuid())
  messageId         String   @unique
  model             String   // "gemini-2-5-flash-preview"
  ttft              Int?     // Time to first token (ms)
  totalTime         Int?     // Total latency (ms)
  graphQueryTime    Int?
  webSearchTime     Int?
  inputTokens       Int
  outputTokens      Int
  thinkingTokens    Int      @default(0)
  toolCalls         Int      @default(0)
  toolCallDetails   Json?
  cost              Float?   // Estimated USD
  cacheHit          Boolean  @default(false)
  cacheCheckTime    Int?
  error             String?
  errorType         String?
  retryCount        Int      @default(0)
  createdAt         DateTime @default(now())
  
  message           Message  @relation(fields: [messageId], references: [id], onDelete: Cascade)
  
  @@map("ai_metrics")
}

model Feedback {
  id        String   @id @default(uuid())
  messageId String
  userId    String
  isLike    Boolean  // true = like, false = dislike
  reason    String?  @db.Text
  createdAt DateTime @default(now())
  updatedAt DateTime @updatedAt
  
  message   Message  @relation(fields: [messageId], references: [id], onDelete: Cascade)
  user      User     @relation(fields: [userId], references: [id])
  
  @@unique([messageId, userId]) // One feedback per user per message
  @@map("feedbacks")
}
```

### Database Migrations

```bash
# Create migration
npx prisma migrate dev --name add_ai_metrics

# Apply migrations
npx prisma migrate deploy

# Generate Prisma Client
npx prisma generate

# Reset database (development only)
npx prisma migrate reset

# Studio (GUI)
npx prisma studio
```

---

## Event-Driven Architecture

### Event Definition

```typescript
// events/conversation-title.event.ts
export class ConversationTitleEvent {
  constructor(
    public readonly conversationId: string,
    public readonly firstQuestion: string,
  ) {}
}
```

### Event Emitter (Publisher)

```typescript
// chat.service.ts
import { EventEmitter2 } from '@nestjs/event-emitter';

@Injectable()
export class ChatService {
  constructor(
    private eventEmitter: EventEmitter2,
  ) {}

  async askAI(...) {
    // ... streaming logic ...

    // Emit event after first message
    if (isFirstMessage) {
      this.eventEmitter.emit(
        'conversation.title_needed',
        new ConversationTitleEvent(conversationId, question),
      );
    }
  }
}
```

### Event Listener (Subscriber)

```typescript
// title-generator.service.ts
import { OnEvent } from '@nestjs/event-emitter';

@Injectable()
export class TitleGeneratorService {
  constructor(
    private httpService: HttpService,
    private conversationsService: ConversationsService,
  ) {}

  @OnEvent('conversation.title_needed', { async: true })
  async handleTitleGeneration(event: ConversationTitleEvent) {
    try {
      // Call FastAPI to generate title
      const response = await this.httpService.post(
        `${FASTAPI_URL}/conversations/generate-title`,
        {
          conversation_id: event.conversationId,
          first_question: event.firstQuestion,
        },
        {
        headers: { 'INTERNAL-SECRET': X_INTERNAL_SECRET },
        },
      ).toPromise();

      // Update conversation title
      await this.conversationsService.update(event.conversationId, {
        title: response.data.title,
      });

      console.log(`✅ Generated title for ${event.conversationId}`);
    } catch (error) {
      console.error(`❌ Failed to generate title: ${error.message}`);
    }
  }
}
```

### Benefits

1. **Non-blocking:** Main request completes immediately
2. **Decoupled:** Title generation is independent
3. **Resilient:** Errors don't affect user experience
4. **Extensible:** Easy to add more listeners (analytics, notifications, etc.)

---

## Rate Limiting

### Configuration

```typescript
// app.module.ts
@Module({
  imports: [
    ThrottlerModule.forRoot([
      {
        name: 'short',
        ttl: 60000,   // 1 minute
        limit: 10,    // 10 requests
      },
      {
        name: 'medium',
        ttl: 1800000, // 30 minutes
        limit: 100,   // 100 requests
      },
      {
        name: 'long',
        ttl: 3600000, // 1 hour
        limit: 200,   // 200 requests
      },
    ]),
    // ...
  ],
})
export class AppModule {}
```

### Usage in Controllers

```typescript
// chat.controller.ts
import { Throttle } from '@nestjs/throttler';

@Controller('chat')
export class ChatController {
  @Post('ask/stream')
  @UseGuards(JwtAuthGuard, ThrottlerGuard)
  @Throttle({ short: { ttl: 60000, limit: 5 } }) // Override: 5 req/min for this endpoint
  async askAI(
    @Body() dto: QuestionDto,
    @GetUser() user: IUser,
    @Res() res: Response,
  ) {
    return this.chatService.askAI(dto.question, dto.conversationId, user.id, res);
  }
}
```

### Custom Throttler Storage (Redis)

```typescript
// redis-throttler.storage.ts
import { ThrottlerStorage } from '@nestjs/throttler';
import { Injectable } from '@nestjs/common';
import Redis from 'ioredis';

@Injectable()
export class RedisThrottlerStorage implements ThrottlerStorage {
  constructor(private redis: Redis) {}

  async increment(key: string, ttl: number): Promise<number> {
    const current = await this.redis.incr(key);
    if (current === 1) {
      await this.redis.expire(key, ttl);
    }
    return current;
  }

  async getRecord(key: string): Promise<number[]> {
    const ttl = await this.redis.ttl(key);
    const count = await this.redis.get(key);
    return [Number(count) || 0, ttl];
  }
}
```

---

## API Endpoints

### Base URL: `http://localhost:8080/api/v1`

### 🔐 Authentication (`/auth`)

| Method | Endpoint | Description | Auth | Rate Limit |
|--------|----------|-------------|------|------------|
| POST | `/register` | Register new user | - | 3/hour |
| POST | `/login` | Login with email/password | - | 10/hour |
| POST | `/refresh-token` | Refresh access token | - | 20/hour |
| POST | `/google/callback` | Google OAuth callback | - | - |
| POST | `/verify-otp` | Verify OTP for password reset | - | 5/hour |
| POST | `/change-password` | Change password | JWT | 5/hour |
| GET | `/profile` | Get current user profile | JWT | - |

**Example: Register**
```bash
curl -X POST http://localhost:8080/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "SecurePass123!",
    "fullName": "Nguyen Van A"
  }'
```

**Response:**
```json
{
  "statusCode": 201,
  "message": "User registered successfully",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
    "user": {
      "id": "uuid",
      "email": "user@example.com",
      "fullName": "Nguyen Van A",
      "role": "USER"
    }
  }
}
```

### Chat (`/chat`)

| Method | Endpoint | Description | Auth | Rate Limit |
|--------|----------|-------------|------|------------|
| POST | `/ask/stream` | Ask question (SSE stream) | JWT | 5/min |
| POST | `/regenerate/:messageId` | Regenerate failed message | JWT | 10/hour |
| GET | `/law-detail/:nodeId` | Get law node detail from Neo4j | JWT | 50/hour |

**Example: Ask Question (Stream)**
```bash
curl -X POST http://localhost:8080/api/v1/chat/ask/stream \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Không đội mũ bảo hiểm bị phạt bao nhiêu?",
    "conversationId": "uuid-or-null"
  }'
```

**SSE Response:**
```
data: {"type":"thought","content":"Đang phân tích câu hỏi..."}

data: {"type":"answer","content":"Theo Nghị định 168/2024..."}

data: {"type":"metadata","sources":[...]}

data: {"type":"done"}
```

### Conversations (`/conversations`)

| Method | Endpoint | Description | Auth | Policy |
|--------|----------|-------------|------|--------|
| GET | `/` | List user's conversations (paginated) | JWT | Own conversations |
| POST | `/` | Create new conversation | JWT | - |
| GET | `/:id` | Get conversation detail | JWT | Own conversation |
| PUT | `/:id` | Update title/summary | JWT | Own conversation |
| DELETE | `/:id` | Soft delete conversation | JWT | Own conversation |

**Example: List Conversations**
```bash
curl -X GET "http://localhost:8080/api/v1/conversations?page=1&limit=20" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

**Response:**
```json
{
  "statusCode": 200,
  "message": "Conversations retrieved successfully",
  "data": {
    "items": [
      {
        "id": "uuid",
        "title": "Hỏi về mức phạt không đội mũ bảo hiểm",
        "summary": null,
        "createdAt": "2024-04-01T10:00:00Z",
        "updatedAt": "2024-04-01T10:05:00Z",
        "messageCount": 6
      }
    ],
    "meta": {
      "total": 45,
      "page": 1,
      "limit": 20,
      "totalPages": 3
    }
  }
}
```

### Messages (`/messages`)

| Method | Endpoint | Description | Auth | Policy |
|--------|----------|-------------|------|--------|
| GET | `/` | Get messages of a conversation | JWT | Own conversation |
| GET | `/:id` | Get single message | JWT | Own conversation |
| DELETE | `/:id` | Delete message | JWT | Own message |

**Example: Get Messages**
```bash
curl -X GET "http://localhost:8080/api/v1/messages?conversationId=uuid" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

### Feedbacks (`/feedbacks`)

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| POST | `/:messageId` | Submit feedback (like/dislike) | JWT |
| GET | `/statistics` | Get feedback statistics | JWT + ADMIN |

**Example: Submit Feedback**
```bash
curl -X POST http://localhost:8080/api/v1/feedbacks/message-uuid \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "isLike": true,
    "reason": "Câu trả lời rất chính xác và dễ hiểu"
  }'
```

### Users (`/users`)

| Method | Endpoint | Description | Auth | Policy |
|--------|----------|-------------|------|--------|
| GET | `/me` | Get current user profile | JWT | - |
| PUT | `/me` | Update profile | JWT | Own profile |
| DELETE | `/me` | Delete account (soft) | JWT | Own account |

### Admin (`/admin`)

| Method | Endpoint | Description | Auth | Policy |
|--------|----------|-------------|------|--------|
| GET | `/users` | List all users | JWT | ADMIN |
| GET | `/conversations/analytics` | System analytics | JWT | ADMIN |
| POST | `/cache/clear` | Clear Redis cache | JWT | ADMIN |

---

## Configuration

### Environment Variables

```env
# Server
PORT=8080
NODE_ENV=development

# Database (PostgreSQL)
DATABASE_URL=postgresql://user:password@localhost:5432/chatbot_law

# JWT
JWT_ACCESS_SECRET=your_random_secret_min_32_chars
JWT_ACCESS_EXPIRED=1d
JWT_REFRESH_SECRET=your_another_random_secret
JWT_REFRESH_EXPIRED=15d

# Redis (Cache, Sessions, Rate Limiting)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=

# Google OAuth (Optional)
GOOGLE_CLIENT_ID=xxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxxxx
GOOGLE_REDIRECT_URI=http://localhost:8080/api/v1/auth/google/callback
BROWSER_REDIRECT_URI=http://localhost:5173?token=

# Email (Nodemailer)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_SECURE=false
EMAIL_USER=your_email@gmail.com
EMAIL_PASSWORD=your_app_password
MAIL_FROM="Chatbot Luật" <no-reply@chatbotluat.vn>

# FastAPI AI Service
FASTAPI_URL=127.0.0.1
FASTAPI_PORT=8001
X_INTERNAL_SECRET=random_secret_for_internal_api

# Frontend
FE_DOMAIN=http://localhost:5173

# Swagger API Docs
SWAGGER_ENABLED=true
```

### ConfigService Usage

```typescript
import { ConfigService } from '@nestjs/config';

@Injectable()
export class SomeService {
  constructor(private configService: ConfigService) {}

  someMethod() {
    const port = this.configService.get<number>('PORT');
    const jwtSecret = this.configService.get<string>('JWT_ACCESS_SECRET');
    const isDevelopment = this.configService.get('NODE_ENV') === 'development';
  }
}
```

---

## Testing

### Unit Tests

```bash
# Run all unit tests
npm run test

# Run tests in watch mode
npm run test:watch

# Coverage report
npm run test:cov
```

**Example Unit Test:**
```typescript
// auth.service.spec.ts
describe('AuthService', () => {
  let service: AuthService;
  let usersService: UsersService;

  beforeEach(async () => {
    const module: TestingModule = await Test.createTestingModule({
      providers: [
        AuthService,
        {
          provide: UsersService,
          useValue: {
            findByEmail: jest.fn(),
            create: jest.fn(),
          },
        },
      ],
    }).compile();

    service = module.get<AuthService>(AuthService);
    usersService = module.get<UsersService>(UsersService);
  });

  describe('register', () => {
    it('should create a new user', async () => {
      const dto = {
        email: 'test@example.com',
        password: 'password123',
        fullName: 'Test User',
      };

      jest.spyOn(usersService, 'findByEmail').mockResolvedValue(null);
      jest.spyOn(usersService, 'create').mockResolvedValue({
        id: 'uuid',
        ...dto,
        role: Role.USER,
      });

      const result = await service.register(dto);
      expect(result.user.email).toBe(dto.email);
    });
  });
});
```

### E2E Tests

```bash
# Run e2e tests
npm run test:e2e
```

**Example E2E Test:**
```typescript
// chat.e2e-spec.ts
describe('ChatController (e2e)', () => {
  let app: INestApplication;
  let authToken: string;

  beforeAll(async () => {
    const moduleFixture: TestingModule = await Test.createTestingModule({
      imports: [AppModule],
    }).compile();

    app = moduleFixture.createNestApplication();
    await app.init();

    // Login to get token
    const response = await request(app.getHttpServer())
      .post('/api/v1/auth/login')
      .send({ email: 'test@example.com', password: 'password' });
    
    authToken = response.body.data.access_token;
  });

  it('/chat/ask/stream (POST)', () => {
    return request(app.getHttpServer())
      .post('/api/v1/chat/ask/stream')
      .set('Authorization', `Bearer ${authToken}`)
      .send({ question: 'Test question', conversationId: null })
      .expect(200);
  });

  afterAll(async () => {
    await app.close();
  });
});
```

---

## Troubleshooting

### Prisma Connection Issues

```bash
# Check DATABASE_URL format
echo $DATABASE_URL
# Should be: postgresql://user:password@host:5432/database

# Test connection
npx prisma db pull

# Reset database (dev only)
npx prisma migrate reset
```

### Redis Connection Failed

```bash
# Check Redis is running
redis-cli ping
# Should return: PONG

# Test from Node.js
node -e "const Redis = require('ioredis'); const redis = new Redis(); redis.ping().then(console.log)"
```

### JWT Token Invalid

```bash
# Verify token
node -e "const jwt = require('jsonwebtoken'); console.log(jwt.decode('YOUR_TOKEN'))"

# Check JWT_ACCESS_SECRET matches
# Compare .env with token signing
```

### Rate Limit Too Strict

```typescript
// Temporarily disable for testing
@UseGuards(JwtAuthGuard) // Remove ThrottlerGuard
@SkipThrottle()          // Or use @SkipThrottle() decorator
async askAI(...) {}
```

### Streaming Not Working

1. **Check Content-Type:**
```typescript
res.setHeader('Content-Type', 'text/event-stream');
res.setHeader('Cache-Control', 'no-cache');
res.setHeader('Connection', 'keep-alive');
```

2. **Disable compression for SSE:**
```typescript
// main.ts
app.use(compression({
  filter: (req, res) => {
    if (req.path.includes('stream')) return false;
    return compression.filter(req, res);
  },
}));
```

3. **Check CORS:**
```typescript
app.enableCors({
  origin: process.env.FE_DOMAIN,
  credentials: true,
});
```

---

## Performance Tips

### Database Optimization

```prisma
// Add indices for frequent queries
@@index([userId, isDeleted])
@@index([conversationId, createdAt])
```

### Redis Caching

```typescript
// Cache conversation list
const cacheKey = `user:${userId}:conversations`;
const cached = await this.redis.get(cacheKey);
if (cached) return JSON.parse(cached);

const conversations = await this.prisma.conversation.findMany({...});
await this.redis.setex(cacheKey, 300, JSON.stringify(conversations)); // 5 min TTL
```

### Query Optimization

```typescript
// Use select to limit fields
const user = await this.prisma.user.findUnique({
  where: { id },
  select: {
    id: true,
    email: true,
    fullName: true,
    // Don't select password
  },
});

// Use include for relations
const conversation = await this.prisma.conversation.findUnique({
  where: { id },
  include: {
    messages: {
      orderBy: { createdAt: 'asc' },
      take: 50, // Limit messages
    },
  },
});
```

---

## Best Practices

1. **Always use DTOs** with class-validator
2. **Implement error handling** với exception filters
3. **Use Interceptors** để standardize responses
4. **Log all errors** với proper context
5. **Use transactions** cho multi-step operations
6. **Implement health checks** cho monitoring
7. **Use environment variables** cho config
8. **Never expose sensitive data** in API responses
9. **Implement pagination** cho list endpoints
10. **Use soft delete** thay vì hard delete

---

## Related Documentation

- [Main README](../README.md)
- [AI Service Documentation](../ai-service/README.md)
- [NestJS Official Docs](https://docs.nestjs.com/)
- [Prisma Documentation](https://www.prisma.io/docs)
- [CASL Authorization](https://casl.js.org/v6/en/)

---
