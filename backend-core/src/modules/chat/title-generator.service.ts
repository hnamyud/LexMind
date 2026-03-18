import { Injectable, Logger } from '@nestjs/common';
import { OnEvent } from '@nestjs/event-emitter';
import { HttpService } from '@nestjs/axios';
import { ConfigService } from '@nestjs/config';
import { ConversationsService } from 'src/modules/conversations/conversations.service';
import {
  CONVERSATION_TITLE_EVENT,
  ConversationTitleEvent,
} from './events/conversation-title.event';

@Injectable()
export class TitleGeneratorService {
  private readonly logger = new Logger(TitleGeneratorService.name);

  constructor(
    private readonly httpService: HttpService,
    private readonly configService: ConfigService,
    private readonly conversationsService: ConversationsService,
  ) {}

  /**
   * Lắng nghe event 'conversation.title_needed'.
   * Được gọi bất đồng bộ, hoàn toàn không block API chat của user.
   *
   * Luồng:
   * 1. Gọi FastAPI /conversations/generate-title (dùng llm_router — model nhẹ)
   * 2. Nhận title string
   * 3. Update conversation.title trong DB
   */
  @OnEvent(CONVERSATION_TITLE_EVENT, { async: true })
  async handleTitleGeneration(event: ConversationTitleEvent): Promise<void> {
    const { conversationId, userMessage, botMessage } = event;
    this.logger.log(`[TitleGenerator] Bắt đầu sinh tiêu đề cho conv: ${conversationId}`);

    const secret = this.configService.get<string>('X-Internal-Secret');
    const fastApiUrl = this.configService.get<string>('FASTAPI_URL');
    const fastApiPort = this.configService.get<string>('FASTAPI_PORT');

    try {
      const response = await this.httpService.axiosRef.post<{ title: string }>(
        `http://${fastApiUrl}:${fastApiPort}/conversations/generate-title`,
        {
          user_message: userMessage,
          bot_message: botMessage,
        },
        {
          headers: { 'X-Internal-Secret': secret },
          // Timeout riêng cho title generation — không cần quá lâu
          timeout: 30_000,
        },
      );

      const title = response.data?.title?.trim();
      if (!title) {
        this.logger.warn(`[TitleGenerator] FastAPI trả về title rỗng cho conv: ${conversationId}`);
        return;
      }

      await this.conversationsService.updateConversation(conversationId, title);
      this.logger.log(`[TitleGenerator] ✅ Đã cập nhật tiêu đề conv ${conversationId}: "${title}"`);
    } catch (err) {
      // Lỗi này không ảnh hưởng đến trải nghiệm user — chỉ log lại
      this.logger.error(
        `[TitleGenerator] ❌ Lỗi sinh tiêu đề cho conv ${conversationId}:`,
        err?.message ?? err,
      );
    }
  }
}
