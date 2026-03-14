import { HttpService } from '@nestjs/axios';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
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
    private readonly configService: ConfigService,
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
    return this._streamFromAI(question, conversation_id, res, userMsg.id);
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

    // 3. Xóa tin nhắn AI bị lỗi (Lưu ý: Bạn cũng cần viết API gọi sang backend Python AI để xóa tin này khỏi memory checkpointer)
    await this.messageService.deleteMessage(messageId);

    // Xoá checkpoint trong bộ nhớ LangGraph qua API vừa tạo ở FastAPI
    try {
      const secret = this.configService.get<string>('X-Internal-Secret');
      const fastApiUrl = this.configService.get<string>('FASTAPI_URL');
      const fastApiPort = this.configService.get<string>('FASTAPI_PORT');

      await this.httpService.axiosRef.delete(`http://${fastApiUrl}:${fastApiPort}/conversations/${conversationId}/checkpoints`, {
        headers: { 'X-Internal-Secret': secret },
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
    return this._streamFromAI(questionText, conversationId, res, parentId); // Giữ nguyên parentId để message bot mới map đúng vào.
  }

  // ============== HELPER STREAM AI ==============
  private async _streamFromAI(question: string, conversation_id: string, res: Response, parentMsgId: string) {
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

    const secret = this.configService.get<string>('X-Internal-Secret');
    const fastApiUrl = this.configService.get<string>('FASTAPI_URL');
    const fastApiPort = this.configService.get<string>('FASTAPI_PORT');

    const response = await this.httpService.axiosRef.post(
      `http://${fastApiUrl}:${fastApiPort}/ask/stream`,
      { question, conversation_id: conversation_id },
      {
        responseType: 'stream',
        signal,
        headers: { 'X-Internal-Secret': secret },
      },
    );

    let fullResponse = '';
    let thoughtResponse = '';
    let metadata = {};
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
        
        // Trả về ID của bot message vừa tạo
        res.write(`data: ${JSON.stringify({ type: 'message_id', messageId: botMsg.id })}\n\n`);
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
}
