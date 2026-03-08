import { Injectable } from '@nestjs/common';
import { ThrottlerGuard } from '@nestjs/throttler';
import { ExecutionContext } from '@nestjs/common';
import { UserRole } from '../enum/role.enum';

@Injectable()
export class AppThrottlerGuard extends ThrottlerGuard {
  public async canActivate(context: ExecutionContext): Promise<boolean> {
    const request = context.switchToHttp().getRequest();
    
    // Custom logic - Skip rate limiting for admin users
    if (request.user?.role === UserRole.ADMIN) {
      return true;
    }

    // Skip rate limiting for specific endpoints
    const skipPaths = [
      '/api/v1/docs',
      '/docs',
    ];
    
    if (skipPaths.some(path => request.url.startsWith(path))) {
      return true;
    }

    return super.canActivate(context);
  }

  protected async getTracker(req: Record<string, any>): Promise<string> {
    // Custom tracking - combine IP + User ID if authenticated
    const ip = req.ip;
    const userId = req.user?.id;
    
    return userId ? `${ip}-${userId}` : ip;
  }
}