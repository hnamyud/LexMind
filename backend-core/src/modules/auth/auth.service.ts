import { BadRequestException, Inject, Injectable, UnauthorizedException } from '@nestjs/common';
import ms, { StringValue } from 'ms';
import { ConfigService } from '@nestjs/config';
import { JwtService } from '@nestjs/jwt';
import { Response } from 'express';
import { PrismaService } from 'prisma/prisma.service';
import { UserRole } from 'src/common/enum/role.enum';
import { IUser } from 'src/common/interfaces/users.interface';
import { RegisterUserDto } from 'src/modules/users/dto/create-user.dto';
import { UsersService } from 'src/modules/users/users.service';
import { ResetPasswordDto } from './dto/reset-password.dto';
import { ChangePasswordDto } from 'src/modules/auth/dto/change-password.dto';
import Redis from 'ioredis';

@Injectable()
export class AuthService {
    constructor(
        private jwtService: JwtService,
        private configService: ConfigService,
        private userService: UsersService,
        private prisma: PrismaService,
        @Inject('REDIS_CLIENT') private redisClient: Redis
    ) { }

    async validateUser(email: string, pass: string): Promise<any> {
        const user = await this.userService.findOneByEmail(email);
        if (user) {
            const isValid = await this.userService.isValidPassword(pass, user.password);
            if (isValid) {
                return user;
            }
        }
        return null;
    }

    async createRefreshToken(payload: any) {
        const refreshToken = this.jwtService.sign(payload, {
            secret: this.configService.get<string>('JWT_REFRESH_SECRET'),
            expiresIn: this.configService.get<string>('JWT_REFRESH_EXPIRED') as any,
        });
        return refreshToken;
    }

    async processToken(refreshToken: string, response: Response) {
        try {
            this.jwtService.verify(refreshToken, {
                secret: this.configService.get<string>('JWT_REFRESH_SECRET')
            })

            let user = await this.userService.queryUserByToken(refreshToken);
            if (!user) {
                throw new BadRequestException('Refresh token không hợp lệ!');
            }
            const { id, email, role } = user;
            const payload = {
                sub: "Access token",
                iss: "Backend-core",
                id,
                email,
                role
            }
            const newRefreshToken = await this.createRefreshToken(payload);
            await this.userService.updateUserToken(newRefreshToken, id);
            // Delete old refresh token
            response.clearCookie('refresh_token');
            // Set new refresh token
            response.cookie('refresh_token', newRefreshToken, {
                httpOnly: true,
                secure: process.env.NODE_ENV === 'production',
                sameSite: 'strict',
                maxAge: ms(this.configService.get<string>('JWT_REFRESH_EXPIRED') as StringValue),
            });

            return {
                accessToken: this.jwtService.sign(payload),
                user: {
                    id,
                    email,
                    role
                }
            };
        }
        catch (error) {
            throw new BadRequestException('Refresh token không hợp lệ!');
        }
    }

    async register(user: RegisterUserDto) {
        let newUser = await this.userService.registerUser(user);
        return {
            id: newUser.id,
            createdAt: newUser.createdAt
        };
    }

    async login(user: IUser, response: Response) {
        const { id, email, role } = user;
        const payload = {
            sub: "Access token",
            iss: "Backend-core",
            id,
            email,
            role
        }

        const refreshToken = await this.createRefreshToken(payload);
        await this.userService.updateUserToken(refreshToken, id);

        response.cookie('refresh_token', refreshToken, {
            httpOnly: true,
            secure: process.env.NODE_ENV === 'production',
            sameSite: 'strict',
            maxAge: ms(this.configService.get<string>('JWT_REFRESH_EXPIRED') as StringValue),
        });

        return {
            accessToken: this.jwtService.sign(payload),
            user: {
                id,
                email,
                role
            }
        };
    }

    async logout(user: IUser, response: Response) {
        try {
            // Remove refresh token from database
            await this.prisma.user.update({
                where: {
                    id: user.id
                },
                data: {
                    refreshToken: null
                }
            });
            // Clear refresh token cookie
            response.clearCookie('refresh_token', {
                httpOnly: true,
                secure: process.env.NODE_ENV === 'production',
                sameSite: 'strict',
                path: '/',
            });

            // Optional
            response.clearCookie('access_token', {
                httpOnly: true,
                secure: process.env.NODE_ENV === 'production',
                sameSite: 'strict',
                path: '/',
            });

            return {
                message: 'Đăng xuất thành công!',
                loggedOut: true,
                timestamp: new Date().toISOString()
            };
        } catch (error) {
            throw new UnauthorizedException('Đăng xuất thất bại!');
        }
    }

    async verifyAdminAccess(user: IUser) {
        if (user.role !== UserRole.ADMIN) {
            throw new UnauthorizedException('Truy cập bị từ chối!');
        }
        return true;
    }

    // Validate Google User OAuth2.0
    async validateGoogleUser(
        googleUser: {
            email: string,
            name: string,
            password?: string
        }
    ): Promise<any> {
        const user = await this.userService.findOneByEmail(googleUser.email);
        if (user) {
            return user;
        }
        return await this.userService.createGoogleUser({
            name: googleUser.name,
            email: googleUser.email,
        });
    }

    async verifyOtp(email: string, otp: string) {
        const redisKey = `reset_otp:${email}`;
        const attemptsKey = `reset_otp_attempts:${email}`;
        const attempts = await this.redisClient.get(attemptsKey);

        // Check number of attempts
        if (attempts && parseInt(attempts) >= 5) {
            await this.redisClient.del(redisKey); // Delete OTP from Redis
            await this.redisClient.del(attemptsKey);
            throw new BadRequestException('Bạn đã nhập sai OTP quá nhiều lần! Vui lòng yêu cầu OTP mới.');
        }

        const storedOtp = await this.redisClient.get(redisKey);
        if (!storedOtp) {
            throw new BadRequestException('OTP không hợp lệ hoặc đã hết hạn!');
        }
        if (storedOtp !== otp) {
            // Increase number of attempts
            await this.redisClient.incr(attemptsKey);

            // Set time to live for this key (example 5 minutes = equal to OTP time)
            await this.redisClient.expire(attemptsKey, 300);
            throw new BadRequestException('OTP không hợp lệ!');
        }

        // If correct, delete the key count (so that the next time the user resets, they don't get stuck with the old limit)
        await this.redisClient.del(attemptsKey);
        return true;
    }

    async resetPassword(resetPasswordDto: ResetPasswordDto) {
        // Kiểm tra OTP và limit thử
        await this.verifyOtp(resetPasswordDto.email, resetPasswordDto.otp);

        const redisKey = `reset_otp:${resetPasswordDto.email}`;

        const user = await this.userService.findOneByEmail(resetPasswordDto.email);
        if (!user) {
            // Case hiếm: Có OTP trong Redis nhưng User lại bị xóa khỏi DB rồi
            throw new BadRequestException('Không tìm thấy tài khoản!');
        }
        const hashPassword = await this.userService.getHashPassword(resetPasswordDto.newPassword);
        await this.userService.updateUserPassword(resetPasswordDto.email, hashPassword);
        // Xoá OTP sau khi đổi mật khẩu thành công
        await this.redisClient.del(redisKey);
    }

    async changePassword(userId: string, changePasswordDto: ChangePasswordDto) {
        return await this.userService.changePassword(userId, changePasswordDto.oldPassword, changePasswordDto.newPassword);
    }

    async getUserInfo(user: IUser) {
        return await this.prisma.user.findUnique({
            where: {
                id: user.id
            },
            select: {
                id: true,
                fullName: true,
                email: true,
                role: true,
                createdAt: true,
            }
        });
    }
}
