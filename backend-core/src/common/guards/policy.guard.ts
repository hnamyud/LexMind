import { Injectable, CanActivate, ExecutionContext, ForbiddenException } from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import { CaslAbilityFactory, AppAbility } from '../../core/casl/ability.factory';
import { CHECK_POLICIES_KEY, PolicyHandler } from '../../core/decorators/policy.decorator';
import { IS_PUBLIC_KEY } from '../../core/decorators/customize.decorator';

@Injectable()
export class PoliciesGuard implements CanActivate {
    constructor(
        private reflector: Reflector,
        private caslAbilityFactory: CaslAbilityFactory,
    ) { }

    async canActivate(context: ExecutionContext): Promise<boolean> {
        const isPublic = this.reflector.getAllAndOverride<boolean>(IS_PUBLIC_KEY, [
            context.getHandler(),
            context.getClass(),
        ]);

        if (isPublic) {
            return true;
        }

        const policyHandlers =
            this.reflector.get<PolicyHandler[]>(
                CHECK_POLICIES_KEY,
                context.getHandler(),
            ) || [];

        // Nếu không định nghĩa policy nào thì coi như đi qua
        if (policyHandlers.length === 0) {
            return true;
        }

        const request = context.switchToHttp().getRequest();
        const user = request.user;

        // Tạo ability cho user đang gọi API
        const ability = this.caslAbilityFactory.createForUser(user);

        // Kiểm tra tất cả các handler được khai báo trong decorator
        for (const handler of policyHandlers) {
            let isAllowed = false;
            if (typeof handler === 'function') {
                isAllowed = (handler as any)(ability);
            } else {
                isAllowed = handler.handle(ability);
            }

            if (!isAllowed) {
                throw new ForbiddenException(handler.message || 'Bạn không có quyền thực hiện hành động này!');
            }
        }

        return true;
    }
}
