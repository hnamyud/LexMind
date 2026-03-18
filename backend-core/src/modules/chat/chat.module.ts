import { Module } from '@nestjs/common';
import { HttpModule } from '@nestjs/axios';
import { ChatService } from './chat.service';
import { ChatController } from './chat.controller';
import { PrismaModule } from 'prisma/prisma.module';
import { MessagesModule } from '../messages/messages.module';
import { ConversationsModule } from '../conversations/conversations.module';
import { TitleGeneratorService } from './title-generator.service';

@Module({
  imports: [
    PrismaModule,
    MessagesModule,
    ConversationsModule,
    HttpModule
  ],
  controllers: [ChatController],
  providers: [ChatService, TitleGeneratorService]
})
export class ChatModule { }
