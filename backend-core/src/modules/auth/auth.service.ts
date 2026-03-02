import { BadRequestException, Injectable, UnauthorizedException } from '@nestjs/common';
import ms, { StringValue } from 'ms';
import { ConfigService } from '@nestjs/config';
import { JwtService } from '@nestjs/jwt';
import { Response } from 'express';
import { PrismaService } from 'prisma/prisma.service';
import { UserRole } from 'src/common/enum/role.enum';
import { IUser } from 'src/common/interfaces/users.interface';
import { RegisterUserDto } from 'src/modules/users/dto/create-user.dto';
import { UsersService } from 'src/modules/users/users.service';

@Injectable()
export class AuthService {
    constructor(
        private jwtService: JwtService,
        private configService: ConfigService,
        private userService: UsersService,
        private prisma: PrismaService,
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
                throw new BadRequestException('Invalid refresh token');
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
            throw new BadRequestException('Invalid refresh token');
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

    async logout(response: Response, user: IUser) {
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
                message: 'Logout successfully',
                loggedOut: true,
                timestamp: new Date().toISOString()
            };
        } catch (error) {
            throw new UnauthorizedException('Logout failed');
        }
    }

    async verifyAdminAccess(user: IUser) {
        if (user.role !== UserRole.ADMIN) {
            throw new UnauthorizedException('Admin access required');
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
}
