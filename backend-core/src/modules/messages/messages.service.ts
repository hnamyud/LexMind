import { Injectable } from '@nestjs/common';
import { PrismaService } from 'prisma/prisma.service';
import { ConversationsService } from '../conversations/conversations.service';
import { IUser } from 'src/common/interfaces/users.interface';

@Injectable()
export class MessagesService {
    constructor(
        private prisma: PrismaService,
        private conversationService: ConversationsService,
    ) { }

    async createMessage(data: {
        conversationId: string;
        sender: string;
        content: string;
        parentId?: string;
        metadata?: any;
    }) {
        return await this.prisma.$transaction([
            this.prisma.message.create({
                data: {
                    conversationId: data.conversationId,
                    sender: data.sender,
                    content: data.content,
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
}
