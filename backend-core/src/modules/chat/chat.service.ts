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

    // Gọi FastAPI AI service
    const response = await this.httpService.axiosRef.post(
      'http://127.0.0.1:8001/ask/stream',
      { question, conversation_id: conversation_id },
      { responseType: 'stream' }
    );

    let fullResponse = '';
    let metadata = {};
    let lineBuffer = '';

    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');

    // Helper: parse một dòng NDJSON và đẩy về Frontend theo chuẩn SSE
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

    response.data.on('data', (chunk: Buffer) => {
      lineBuffer += chunk.toString();
      const lines = lineBuffer.split('\n');
      lineBuffer = lines.pop() || ''; // giữ lại dòng cuối chưa hoàn chỉnh
      for (const line of lines) {
        processLine(line);
      }
    });

    response.data.on('end', async () => {
      // Xử lý nốt phần còn lại trong buffer nếu có
      if (lineBuffer.trim()) {
        processLine(lineBuffer);
        lineBuffer = '';
      }

      // Báo hiệu Frontend đóng kết nối TRƯỚC (không cần chờ DB)
      res.write('data: [DONE]\n\n');
      res.end();

      // Lưu bot message vào DB sau khi đã đóng kết nối frontend
      try {
        await this.messageService.createMessage({
          conversationId: conversation_id,
          sender: 'bot',
          content: fullResponse,
          parentId: userMsg.id,
          metadata: metadata,
        });
      } catch (err) {
        this.logger.error('Lỗi lưu bot message vào DB:', err);
      }
    });

    // Bắt lỗi kết nối FastAPI
    response.data.on('error', (err: Error) => {
      this.logger.error('Lỗi stream từ FastAPI:', err);
      res.write(`data: {"type": "error", "content": "Mất kết nối với AI"}\n\n`);
      res.end();
    });
  }
}
