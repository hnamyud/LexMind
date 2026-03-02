import {
    Injectable,
    CanActivate,
    ExecutionContext,
    ForbiddenException,
    NotFoundException,
} from '@nestjs/common';
import { PrismaService } from 'prisma/prisma.service';

@Injectable()
export class ConversationOwnerGuard implements CanActivate {
    constructor(private prisma: PrismaService) { }

    async canActivate(context: ExecutionContext): Promise<boolean> {
        const request = context.switchToHttp().getRequest();
        const user = request.user; // Lấy từ AuthGuard (JWT)
        const { conversationId } = request.body;

        // 1. Nếu không truyền conversationId, mặc định cho qua (để tạo mới)
        if (!conversationId) {
            return true;
        }

        // 2. Kiểm tra sự tồn tại và quyền sở hữu trong Postgres
        const conversation = await this.prisma.conversation.findUnique({
            where: { id: conversationId },
        });

        if (!conversation) {
            throw new NotFoundException('Không tìm thấy cuộc hội thoại này');
        }

        if (conversation.userId !== user.id) {
            throw new ForbiddenException('Bạn không có quyền truy cập cuộc hội thoại này');
        }

        return true; // Hợp lệ, cho phép request đi tiếp vào Controller
    }
}