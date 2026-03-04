import { BadRequestException, Injectable, UnauthorizedException } from '@nestjs/common';
import { PrismaService } from 'prisma/prisma.service';
import { IUser } from 'src/common/interfaces/users.interface';

@Injectable()
export class ConversationsService {
    constructor(
        private prisma: PrismaService,
    ) { }

    async createConversation(user: IUser, title: string, summary: string) {
        return await this.prisma.conversation.create({
            data: {
                userId: user.id,
                title,
                summary,
                createdAt: new Date(),
            }
        })
    }

    async deleteConversation(id: string) {
        return await this.prisma.conversation.delete({
            where: {
                id: id
            }
        })
    }

    async findAll(currentPage: number, limit: number, user: IUser) {
        let offset = (+currentPage - 1) * (+limit);
        let defaultLimit = +limit ? +limit : 10;

        // Đếm tổng số lượng conversation của user này
        const totalItems = await this.prisma.conversation.count({
            where: { userId: user.id, isDeleted: false }
        });
        const totalPages = Math.ceil(totalItems / defaultLimit);

        // Lấy danh sách conversation sắp xếp theo updatedAt (mới nhất lên đầu)
        const result = await this.prisma.conversation.findMany({
            where: { userId: user.id, isDeleted: false },
            skip: offset,
            take: defaultLimit,
            orderBy: { updatedAt: 'desc' },
            select: {
                id: true,
                title: true,
                summary: true,
                createdAt: true,
                updatedAt: true,
                // Không select messages để list load nhanh
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

    async getConversationById(id: string, user: IUser) {
        const conversation = await this.prisma.conversation.findUnique({
            where: {
                id: id,
                isDeleted: false
            }
        })
        if (!conversation) {
            throw new BadRequestException(`Conversation: ${id} không tồn tại`);
        }
        if (conversation.userId !== user.id) {
            throw new UnauthorizedException('You are not authorized to access this conversation');
        }
        return conversation;
    }

    async updateConversation(id: string, title: string, summary?: string) {
        return await this.prisma.conversation.update({
            where: {
                id: id
            },
            data: {
                title,
                summary,
                updatedAt: new Date(),
            }
        })
    }

    async softDeleteConversation(id: string) {
        return await this.prisma.conversation.update({
            where: {
                id: id
            },
            data: {
                isDeleted: true,
                deletedAt: new Date(),
            }
        })
    }
}
