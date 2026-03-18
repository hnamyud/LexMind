import { MiddlewareConsumer, Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { EventEmitterModule } from '@nestjs/event-emitter';
import { AppController } from './app.controller';
import { AppService } from './app.service';
import { ConversationsModule } from './modules/conversations/conversations.module';
import { AuthModule } from './modules/auth/auth.module';
import { UsersModule } from './modules/users/users.module';
import { MessagesModule } from './modules/messages/messages.module';
import { ChatModule } from './modules/chat/chat.module';
import { HttpModule } from '@nestjs/axios';
import { MailModule } from './shared/mailer/mail.module';
import { RedisModule } from './shared/cache/redis.module';
import { LoggerMiddleware } from './core/middleware/logger.middleware';
import { CaslModule } from './core/casl/casl.module';
import { FeedbacksModule } from './modules/feedbacks/feedbacks.module';
import { ThrottlerModule } from '@nestjs/throttler';
import { AppThrottlerGuard } from './common/guards/app-throttler.guard';
import { APP_GUARD } from '@nestjs/core';

@Module({
  imports: [
    CaslModule,
    FeedbacksModule,
    EventEmitterModule.forRoot(), // Global event bus — fire-and-forget pattern
    ConfigModule.forRoot({
      isGlobal: true,
      envFilePath: '../.env', // Root .env dùng chung với ai-service
    }),
    HttpModule.register({
      timeout: 60000, // AI có thể suy nghĩ lâu nên để timeout dài
      maxRedirects: 5,
    }),
    ThrottlerModule.forRoot({
      throttlers: [
        {
          name: 'short', 
          ttl: 60000,    // 60 seconds = 1 minute
          limit: 10,    
        },
        {
          name: 'medium', 
          ttl: 1800000,    // 30 minutes  
          limit: 100,     
        },
        {
          name: 'long',   
          ttl: 3600000,   // 1 hour
          limit: 200,    
        }
      ],
    }),
    ConversationsModule,
    MailModule,
    AuthModule,
    UsersModule,
    MessagesModule,
    ChatModule,
    RedisModule,
  ],
  controllers: [AppController],
  providers: [
    AppService,
    {
      provide: APP_GUARD,
      useClass: AppThrottlerGuard,
    }
  ],
})
export class AppModule {
  // Configure middleware globally
  configure(consumer: MiddlewareConsumer) {
    consumer
      .apply(LoggerMiddleware)
      .forRoutes('*');
  }
}
