/**
 * Event được emit ngay sau khi bot message đầu tiên của một conversation
 * được lưu thành công vào DB.
 *
 * NestJS EventEmitter sẽ fire-and-forget event này để
 * TitleGeneratorService xử lý bất đồng bộ hoàn toàn,
 * không block luồng stream trả về cho user.
 */
export class ConversationTitleEvent {
  constructor(
    /** ID của conversation cần đặt tiêu đề */
    public readonly conversationId: string,
    /** Câu hỏi gốc của user (tin nhắn đầu tiên) */
    public readonly userMessage: string,
    /** Câu trả lời đầu tiên của bot */
    public readonly botMessage: string,
  ) {}
}

/** Tên event dùng để đăng ký listener và emit */
export const CONVERSATION_TITLE_EVENT = 'conversation.title_needed';
