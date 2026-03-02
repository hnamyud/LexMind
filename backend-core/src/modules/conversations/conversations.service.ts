import { Injectable } from '@nestjs/common';
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

    async getConversationById(id: string) {
        return await this.prisma.conversation.findUnique({
            where: {
                id: id
            }
        })
    }

    async updateConversation(id: string, title: string, summary: string) {
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
}
