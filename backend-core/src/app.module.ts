import { MiddlewareConsumer, Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
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

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      envFilePath: '../.env', // Root .env dùng chung với ai-service
    }),
    HttpModule.register({
      timeout: 60000, // AI có thể suy nghĩ lâu nên để timeout dài
      maxRedirects: 5,
    }),
    ConversationsModule,
    MailModule,
    AuthModule,
    UsersModule,
    MessagesModule,
    ChatModule,
    RedisModule
  ],
  controllers: [AppController],
  providers: [AppService],
})
export class AppModule {
  // Configure middleware globally
  configure(consumer: MiddlewareConsumer) {
    consumer
      .apply(LoggerMiddleware)
      .forRoutes('*');
  }
}
