import { HttpService } from '@nestjs/axios';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { EventEmitter2 } from '@nestjs/event-emitter';
import type { Response } from 'express';
import { PrismaService } from 'prisma/prisma.service';
import { MessagesService } from '../messages/messages.service';
import { ConversationsService } from '../conversations/conversations.service';
import { CloudinaryImage } from '../messages/messages.service';
import {
  CONVERSATION_TITLE_EVENT,
  ConversationTitleEvent,
} from './events/conversation-title.event';

@Injectable()
export class ChatService {
  private readonly logger = new Logger(ChatService.name);

  constructor(
    private readonly httpService: HttpService,
    private messageService: MessagesService,
    private conversationService: ConversationsService,
    private readonly configService: ConfigService,
    private readonly eventEmitter: EventEmitter2,
    private readonly prisma: PrismaService,
  ) { }

  async askAI(question: string, conversationId: string, res: Response, image?: CloudinaryImage) {
    let conversation_id = conversationId;

    if (!conversation_id) {
      // Tạo mới conversation nếu chưa có (ví dụ title lấy từ question)
      const user = res.req.user as any;
      const newConv = await this.conversationService.createConversation(
        user,
        question.substring(0, 50) + '...', // Tóm tắt ngắn
        '' // chưa có summary dài
      );
      conversation_id = newConv.id;
    }

    // Lưu câu hỏi của user vào DB
    const [userMsg] = await this.messageService.createMessage({
      conversationId: conversation_id,
      sender: 'user',
      content: question,
      image,
    });

    // AbortController: huỷ khi client đóng tab hoặc nhấn stop
    return this._streamFromAI(question, conversation_id, res, userMsg.id, image);
  }

  async regenerateMessage(messageId: string, res: Response) {
    // 1. Phân tích tin nhắn muốn regenerate
    const messageToRegenerate = await this.messageService.getMessageById(messageId);

    if (messageToRegenerate.sender !== 'bot') {
      throw new Error('Chỉ có thể tạo lại câu trả lời của AI.');
    }

    const conversationId = messageToRegenerate.conversationId;
    const parentId = messageToRegenerate.parentId;

    if (!parentId) {
      throw new Error('Không tìm thấy câu hỏi gốc để tạo lại.');
    }

    // 2. Tìm câu hỏi gốc của user
    const originalQuestionMsg = await this.messageService.getMessageById(parentId);
    const questionText = originalQuestionMsg.content;
    const metadata: any = originalQuestionMsg.metadata || {};
    const image = metadata.image;

    // 3. Xóa tin nhắn AI bị lỗi (Lưu ý: Bạn cũng cần viết API gọi sang backend Python AI để xóa tin này khỏi memory checkpointer)
    await this.messageService.deleteMessage(messageId);

    // Xoá checkpoint trong bộ nhớ LangGraph qua API vừa tạo ở FastAPI
    try {
      const secret = this.configService.get<string>('INTERNAL_SECRET');
      const fastApiUrl = this.configService.get<string>('FASTAPI_URL');
      const fastApiPort = this.configService.get<string>('FASTAPI_PORT');

      await this.httpService.axiosRef.delete(`http://${fastApiUrl}:${fastApiPort}/conversations/${conversationId}/checkpoints`, {
        headers: { 'INTERNAL-SECRET': secret },
      });
      this.logger.log(`[regenerate] Đã xóa checkpoint của conversation: ${conversationId}`);
    } catch (err) {
      this.logger.error(`[regenerate] Lỗi khi xóa checkpoint conversation ${conversationId}:`, err);
    }

    // 4. Bắt đầu trả luồng SSE lại bình thường!
    // Tại đây, bạn KHÔNG NÊN gọi hàm `this.askAI` lại một cách nguyên bản vì:
    // Hàm askAI sẽ TẠO THÊM 1 MESSAGE CÂU HỎI MỚI VÀO DB (do có đoạn await this.messageService.createMessage(..)).
    // Mà trong ngữ cảnh Regenerate, câu hỏi gốc (originalQuestionMsg) VẪN ĐANG NẰM TRONG DB.

    // Vì vậy tôi tách luồng Stream logic thành một Helper method bên dưới để bạn tái sử dụng:
    return this._streamFromAI(questionText, conversationId, res, parentId, image); // Truyền cả image nếu có.
  }

  // ============== HELPER STREAM AI ==============
  private async _streamFromAI(question: string, conversation_id: string, res: Response, parentMsgId: string, image?: CloudinaryImage) {
    const abortController = new AbortController();
    const { signal } = abortController;
    let isAborted = false;

    res.req.on('close', () => {
      if (!isAborted && !res.writableEnded) {
        isAborted = true;
        this.logger.warn(`[streamAI] Client ngắt kết nối — huỷ stream AI (conv: ${conversation_id})`);
        abortController.abort();
      }
    });

    const secret = this.configService.get<string>('INTERNAL_SECRET');
    const fastApiUrl = this.configService.get<string>('FASTAPI_URL');
    const fastApiPort = this.configService.get<string>('FASTAPI_PORT');

    const response = await this.httpService.axiosRef.post(
      `http://${fastApiUrl}:${fastApiPort}/ask/stream`,
      {
        question,
        conversation_id: conversation_id,
        ...(image ? { image } : {}),
      },
      {
        responseType: 'stream',
        signal,
        headers: { 'INTERNAL-SECRET': secret },
      },
    );

    let fullResponse = '';
    let thoughtResponse = '';
    let metadata = {};
    let aiMetrics: any = null;  // Capture AI metrics
    let lineBuffer = '';

    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');

    // Gửi conversationId ngay từ đầu stream để client nhận diện mạch truyện (đặc biệt khi vừa tạo mới)
    res.write(`data: ${JSON.stringify({ type: 'info', conversationId: conversation_id })}\n\n`);

    const processLine = (line: string) => {
      if (!line.trim()) return;
      res.write(`data: ${line}\n\n`);
      try {
        const parsed = JSON.parse(line);
        if (parsed.type === 'answer') fullResponse += parsed.content;
        else if (parsed.type === 'thinking') thoughtResponse += parsed.content;
        else if (parsed.type === 'metadata') metadata = parsed.content;
        else if (parsed.type === 'metrics') aiMetrics = parsed.content; // Capture metrics
      } catch (error) {
        this.logger.error(`Lỗi parse dòng: ${line}`, error);
      }
    };

    response.data.on('data', (chunk: Buffer) => {
      if (isAborted) return;
      lineBuffer += chunk.toString();
      const lines = lineBuffer.split('\n');
      lineBuffer = lines.pop() || '';
      for (const line of lines) processLine(line);
    });

    response.data.on('end', async () => {
      if (isAborted) return;
      if (lineBuffer.trim()) {
        processLine(lineBuffer);
        lineBuffer = '';
      }

      this.logger.log(`[streamAI] Stream ended. fullResponse length: ${fullResponse.length}, thoughtResponse length: ${thoughtResponse.length}`);
      this.logger.debug(`[streamAI] fullResponse preview: ${fullResponse.substring(0, 200)}`);
      this.logger.debug(`[streamAI] thoughtResponse preview: ${thoughtResponse.substring(0, 200)}`);

      try {
        const [botMsg] = await this.messageService.createMessage({
          conversationId: conversation_id,
          sender: 'bot',
          content: fullResponse,
          thought: thoughtResponse,
          parentId: parentMsgId,
          metadata,
        });
        this.logger.log(`[streamAI] Đã lưu bot message — conv: ${conversation_id}`);

        // ━━ Save AI Metrics to database ━━
        if (aiMetrics) {
          try {
            await this.prisma.aIMetrics.create({
              data: {
                messageId: botMsg.id,
                model: aiMetrics.model || 'gemini-3-flash-preview',
                ttft: aiMetrics.ttft,
                totalTime: aiMetrics.totalTime,
                graphQueryTime: aiMetrics.graphQueryTime,
                webSearchTime: aiMetrics.webSearchTime,
                inputTokens: aiMetrics.inputTokens,
                outputTokens: aiMetrics.outputTokens,
                thinkingTokens: aiMetrics.thinkingTokens,
                toolCalls: aiMetrics.toolCalls,
                toolCallDetails: aiMetrics.toolCallDetails,
                cost: aiMetrics.cost,
                error: aiMetrics.error,
                errorType: aiMetrics.errorType,
                cacheHit: aiMetrics.cacheHit ?? false,
                cacheCheckTime: aiMetrics.cacheCheckTime,
                retryCount: 0,
              },
            });
            this.logger.log(`[streamAI] Đã lưu AI metrics cho message: ${botMsg.id}`);
          } catch (metricsErr) {
            this.logger.error('Lỗi lưu AI metrics:', metricsErr);
            // Don't fail the entire request if metrics saving fails
          }
        }

        // Trả về ID của bot message vừa tạo
        res.write(`data: ${JSON.stringify({ type: 'message_id', messageId: botMsg.id })}\n\n`);

        // ━━ Sinh title bất đồng bộ sau khi bot trả lời lần đầu ━━
        // Đếm tổng số messages — chỉ emit khi đây là bot message đầu tiên (tổng = 2)
        const messageCount = await this.messageService.countMessages(conversation_id);
        if (messageCount === 2 && fullResponse.trim()) {
          this.eventEmitter.emit(
            CONVERSATION_TITLE_EVENT,
            new ConversationTitleEvent(conversation_id, question, fullResponse),
          );
          this.logger.log(`[streamAI] Đã emit sự kiện sinh tiêu đề cho conv: ${conversation_id}`);
        }
      } catch (err) {
        this.logger.error('Lỗi lưu bot message vào DB:', err);
      }

      res.write('data: [DONE]\n\n');
      res.end();
    });

    response.data.on('error', async (err: Error) => {
      const isCanceled = isAborted || err.name === 'AbortError' || (err as any).code === 'ERR_CANCELED';
      if (isCanceled) {
        if (!res.writableEnded) res.end();
        return;
      }
      this.logger.error('Lỗi stream từ FastAPI:', err);
      if (!res.writableEnded) {
        res.write(`data: {"type": "error", "content": "Mất kết nối với AI"}\n\n`);
        res.end();
      }
    });
  }

  async getLawDetail(nodeId: string, limit?: string) {
    const fastApiUrl = this.configService.get<string>('FASTAPI_URL');
    const fastApiPort = this.configService.get<string>('FASTAPI_PORT');
    const parsedLimit = Number.parseInt(limit ?? '', 10);
    const safeLimit = Number.isFinite(parsedLimit) && parsedLimit > 0
      ? Math.min(parsedLimit, 100)
      : 25;
    
    try {
      const response = await this.httpService.axiosRef.get(
        `http://${fastApiUrl}:${fastApiPort}/law-detail/${nodeId}`,
        {
          params: { limit: safeLimit },
        },
      );
      return response.data;
    } catch (err) {
      this.logger.error(`Lỗi khi lấy chi tiết điều luật ${nodeId}:`, err);
      throw err;
    }
  }
}
