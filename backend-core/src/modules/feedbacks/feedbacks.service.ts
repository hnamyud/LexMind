import { Injectable, BadRequestException, NotFoundException, ForbiddenException } from '@nestjs/common';
import { PrismaService } from 'prisma/prisma.service';
import { IUser } from 'src/common/interfaces/users.interface';
import { CreateFeedbackDto } from './dto/create-feedback.dto';

@Injectable()
export class FeedbacksService {
    constructor(private prisma: PrismaService) { }

    async upsertFeedback(messageId: string, user: IUser, createFeedbackDto: CreateFeedbackDto) {
        // Kiểm tra tin nhắn có tồn tại không
        const message = await this.prisma.message.findUnique({
            where: { id: messageId },
            include: {
                conversation: true, // Join lấy cả đoạn chat để kiểm tra owner
            },
        });

        if (!message) {
            throw new NotFoundException(`Nhắn tin ID ${messageId} không tồn tại.`);
        }

        // Chỉ cho phép user là chủ của đoạn chat (hoặc nếu luật doanh nghiệp cho phép người khác xem, hãy xử lý thêm theo logic). 
        // Mặc định, người hỏi mới được vote tin nhắn của AI.
        if (message.conversation?.userId !== user.id) {
            throw new ForbiddenException('Bạn không có quyền đánh giá tin nhắn trong đoạn chat này.');
        }

        // Lưu Feedback (Upsert: Nếu đã có thì cập nhật, nếu chưa thì tạo mới)
        return await this.prisma.feedback.upsert({
            where: {
                messageId_userId: {
                    messageId: messageId,
                    userId: user.id,
                },
            },
            update: {
                isLike: createFeedbackDto.isLike,
                reason: createFeedbackDto.reason,
                updatedAt: new Date(),
            },
            create: {
                messageId: messageId,
                userId: user.id,
                isLike: createFeedbackDto.isLike,
                reason: createFeedbackDto.reason,
            },
        });
    }

    // Admin có thể gọi API này để xem chi tiết log feedback
    async fetchFeedbacksByMessage(messageId: string) {
        return await this.prisma.feedback.findMany({
            where: { messageId },
            include: {
                user: { select: { id: true, fullName: true, email: true } },
            },
            orderBy: { createdAt: 'desc' },
        });
    }
}
