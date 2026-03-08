import { Injectable } from '@nestjs/common';
import { PureAbility, AbilityBuilder } from '@casl/ability';
import { PrismaQuery, Subjects, createPrismaAbility } from '@casl/prisma';
import { User, Conversation, Message, Feedback } from '@prisma/client';
import { Action } from '../../common/enum/action.enum';
import { IUser } from '../../common/interfaces/users.interface';
import { UserRole } from 'src/common/enum/role.enum';

// Định nghĩa các entities từ Prisma models
export type AppSubjects = Subjects<{
    User: User;
    Conversation: Conversation;
    Message: Message;
    Feedback: Feedback;
}> | 'all';

// Khởi tạo AppAbility kiểu PureAbility có hỗ trợ PrismaQuery
export type AppAbility = PureAbility<[Action, AppSubjects], PrismaQuery>;

@Injectable()
export class CaslAbilityFactory {
    createForUser(user: IUser) {
        // Sử dụng createPrismaAbility thay vì createMongoAbility
        const { can, cannot, build } = new AbilityBuilder<AppAbility>(createPrismaAbility);

        if (user.role === UserRole.ADMIN) {
            can(Action.Manage, 'all'); // Admin có toàn quyền (Manage là alias cho mọi action, 'all' là mọi subject)
        } else {
            // ==== PHÂN QUYỀN CHO USER THƯỜNG ====

            // 1. Quyền trên chính User (chỉ có thể đọc/sửa thông tin của chính mình)
            can(Action.Read, 'User', { id: user.id });
            can(Action.Update, 'User', { id: user.id });

            // 2. Quyền trên Conversation (Liên kết qua userId)
            can(Action.Create, 'Conversation');
            can(Action.Read, 'Conversation', { userId: user.id });
            can(Action.Update, 'Conversation', { userId: user.id });
            can(Action.Delete, 'Conversation', { userId: user.id });

            // 3. Quyền trên Feedback (Liên kết qua Message)
            can(Action.Create, 'Feedback');
        }

        return build();
    }
}