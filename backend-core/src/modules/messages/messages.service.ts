import { BadRequestException, Injectable } from '@nestjs/common';
import { PrismaService } from 'prisma/prisma.service';
import { ConversationsService } from '../conversations/conversations.service';
import { IUser } from 'src/common/interfaces/users.interface';
import { ChatService } from '../chat/chat.service';

@Injectable()
export class MessagesService {
    constructor(
        private prisma: PrismaService,
        private conversationService: ConversationsService
    ) { }

    async createMessage(data: {
        conversationId: string;
        sender: string;
        content: string;
        thought?: string;
        parentId?: string;
        metadata?: any;
    }) {
        return await this.prisma.$transaction([
            this.prisma.message.create({
                data: {
                    conversationId: data.conversationId,
                    sender: data.sender,
                    content: data.content,
                    thought: data.thought,
                    parentId: data.parentId,
                    metadata: data.metadata,
                },
            }),
            this.prisma.conversation.update({
                where: { id: data.conversationId },
                data: { updatedAt: new Date() },
            }),
        ]);
    }

    async findAll(currentPage: number, limit: number, conversationId: string, user: IUser) {
        await this.conversationService.getConversationById(conversationId, user);

        let offset = (+currentPage - 1) * (+limit);
        let defaultLimit = +limit ? +limit : 10;

        // Đếm tổng số lượng messages của đoạn hội thoại
        const totalItems = await this.prisma.message.count({
            where: { conversationId: conversationId }
        });
        const totalPages = Math.ceil(totalItems / defaultLimit);

        // Lấy danh sách messages sắp xếp theo createdAt (mới nhất lên đầu)
        const result = await this.prisma.message.findMany({
            where: { conversationId: conversationId },
            skip: offset,
            take: defaultLimit,
            orderBy: { createdAt: 'desc' },
            select: {
                id: true,
                content: true,
                sender: true,
                thought: true,
                createdAt: true,
            }
        });

        return {
            meta: {
                current: currentPage, // trang hiện tại
                pageSize: limit, // số lượng bản ghi đã lấy
                pages: totalPages,  // tổng số trang
                total: totalItems // tổng số phần tử
            },
            result // kết quả query
        };
    }

    async deleteMessage(messageId: string) {
        const message = await this.prisma.message.findUnique({
            where: { id: messageId },
        });
        if (!message) {
            throw new BadRequestException(`Message: ${messageId} không tồn tại`);
        }
        return await this.prisma.message.delete({
            where: { id: messageId },
        });
    }

    async getMessageById(messageId: string) {
        const message = await this.prisma.message.findUnique({
            where: { id: messageId },
        });
        if (!message) {
            throw new BadRequestException(`Message: ${messageId} không tồn tại`);
        }
        return message;
    }
}
