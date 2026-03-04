import { HttpService } from '@nestjs/axios';
import { Injectable, Logger } from '@nestjs/common';
import type { Response } from 'express';
import { MessagesService } from '../messages/messages.service';
import { ConversationsService } from '../conversations/conversations.service';

@Injectable()
export class ChatService {
  private readonly logger = new Logger(ChatService.name);

  constructor(
    private readonly httpService: HttpService,
    private messageService: MessagesService,
    private conversationService: ConversationsService,
  ) { }

  async askAI(question: string, conversationId: string, res: Response) {
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
    });

    // AbortController: huỷ khi client đóng tab hoặc nhấn stop
    const abortController = new AbortController();
    const { signal } = abortController;
    let isAborted = false;

    // Lắng nghe sự kiện client ngắt kết nối (đóng tab / nhấn stop)
    res.req.on('close', () => {
      if (!isAborted && !res.writableEnded) {
        isAborted = true;
        this.logger.warn(
          `[askAI] Client ngắt kết nối — huỷ stream AI (conv: ${conversation_id})`,
        );
        abortController.abort();
      }
    });

    // Gọi FastAPI AI service (truyền signal để axios tự huỷ khi abort)
    const response = await this.httpService.axiosRef.post(
      'http://127.0.0.1:8001/ask/stream',
      { question, conversation_id: conversation_id },
      { responseType: 'stream', signal },
    );

    let fullResponse = '';
    let metadata = {};
    let lineBuffer = '';

    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');

    // Helper: ghi 1 dòng SSE và tích luỹ response
    const processLine = (line: string) => {
      if (!line.trim()) return;

      res.write(`data: ${line}\n\n`);

      try {
        const parsed = JSON.parse(line);
        if (parsed.type === 'answer') {
          fullResponse += parsed.content;
        } else if (parsed.type === 'metadata') {
          metadata = parsed.content;
        }
      } catch (error) {
        this.logger.error(`Lỗi parse dòng: ${line}`, error);
      }
    };

    // Helper: lưu bot message khi AI trả lời xong
    const saveBotMessage = async () => {
      try {
        await this.messageService.createMessage({
          conversationId: conversation_id,
          sender: 'bot',
          content: fullResponse,
          parentId: userMsg.id,
          metadata,
        });
        this.logger.log(
          `[askAI] Đã lưu bot message — conv: ${conversation_id}`,
        );
      } catch (err) {
        this.logger.error('Lỗi lưu bot message vào DB:', err);
      }
    };

    // Helper: rollback — xóa user message khi client abort
    const cleanupOnAbort = async () => {
      try {
        await this.messageService.deleteMessage(userMsg.id);
        this.logger.warn(
          `[askAI] Đã xóa user message do client abort — id: ${userMsg.id}`,
        );
      } catch (err) {
        this.logger.error('Lỗi xóa user message khi abort:', err);
      }
    };

    response.data.on('data', (chunk: Buffer) => {
      if (isAborted) return; // Bỏ qua data sau khi đã abort
      lineBuffer += chunk.toString();
      const lines = lineBuffer.split('\n');
      lineBuffer = lines.pop() || ''; // giữ lại dòng cuối chưa hoàn chỉnh
      for (const line of lines) {
        processLine(line);
      }
    });

    response.data.on('end', async () => {
      if (isAborted) return; // 'end' có thể fire sau abort → bỏ qua

      // Xử lý nốt phần còn lại trong buffer
      if (lineBuffer.trim()) {
        processLine(lineBuffer);
        lineBuffer = '';
      }

      // Báo hiệu Frontend đóng kết nối TRƯỚC (không cần chờ DB)
      res.write('data: [DONE]\n\n');
      res.end();

      // Lưu bot message sau khi đã đóng kết nối frontend
      await saveBotMessage();
    });

    // Bắt lỗi stream — bao gồm lỗi cancel từ AbortController
    response.data.on('error', async (err: Error) => {
      const isCanceled =
        isAborted ||
        err.name === 'AbortError' ||
        (err as any).code === 'ERR_CANCELED';

      if (isCanceled) {
        // Client chủ động huỷ → xóa user message (rollback)
        if (!res.writableEnded) res.end();
        await cleanupOnAbort();
        return;
      }

      this.logger.error('Lỗi stream từ FastAPI:', err);
      if (!res.writableEnded) {
        res.write(`data: {"type": "error", "content": "Mất kết nối với AI"}\n\n`);
        res.end();
      }
    });
  }
}
