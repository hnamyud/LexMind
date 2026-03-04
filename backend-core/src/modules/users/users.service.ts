import { BadRequestException, Injectable } from '@nestjs/common';
import { PrismaService } from 'prisma/prisma.service';
import { compare, compareSync, genSaltSync, hashSync } from 'bcryptjs';
import { RegisterUserDto } from './dto/create-user.dto';
import { UserRole } from 'src/common/enum/role.enum';
import { IUser } from 'src/common/interfaces/users.interface';

@Injectable()
export class UsersService {
    constructor(
        private prisma: PrismaService,
    ) { }

    async getHashPassword(password: string) {
        const salt = genSaltSync(10);
        const hash = hashSync(password, salt);
        return hash;
    }

    async isValidPassword(password: string, hash: string) {
        return compareSync(password, hash);
    }

    async findOneByEmail(email: string) {
        return this.prisma.user.findUnique({
            where: {
                email: email
            }
        });
    }

    async updateUserToken(refreshToken: string, id: string) {
        return await this.prisma.user.update({
            where: {
                id: id
            },
            data: {
                refreshToken: refreshToken
            }
        });
    }

    async queryUserByToken(refreshToken: string) {
        return await this.prisma.user.findUnique({
            where: {
                refreshToken: refreshToken
            }
        });
    }

    async registerUser(user: RegisterUserDto) {
        const { name, email, password } = user;
        const isExisted = await this.findOneByEmail(email);
        if (isExisted) {
            throw new BadRequestException(`Email: ${email} đã tồn tại`);
        }
        const hashPassword = await this.getHashPassword(password);
        return await this.prisma.user.create({
            data: {
                fullName: name,
                email,
                password: hashPassword,
                role: UserRole.USER
            }
        });
    }

    async createGoogleUser(googleUser: { email: string; name: string }) {
        const { email, name } = googleUser;
        const isExisted = await this.findOneByEmail(email);
        if (isExisted) {
            throw new BadRequestException(`Email: ${email} đã tồn tại`);
        }

        // Generate a random password for Google users
        const randomPassword = Math.random().toString(36).slice(-8);
        const hashPassword = await this.getHashPassword(randomPassword);

        return await this.prisma.user.create({
            data: {
                fullName: name,
                email,
                password: hashPassword,
                role: UserRole.USER
            }
        });
    }

    async softDeleteUser(id: string) {
        const user = await this.prisma.user.findUnique({
            where: {
                id: id
            }
        });
        if (!user) {
            throw new BadRequestException(`User: ${id} không tồn tại`);
        }
        return await this.prisma.user.update({
            where: {
                id: user.id
            },
            data: {
                deletedAt: new Date()
            }
        });
    }

    async changePassword(id: string, oldPassword: string, newPassword: string) {
        const user = await this.prisma.user.findUnique({
            where: {
                id: id
            }
        });
        if (!user) {
            throw new BadRequestException(`User: ${id} không tồn tại`);
        }
        // Kiểm tra mật khẩu cũ
        const isMatch = await compare(oldPassword, user.password);
        if (!isMatch) {
            throw new BadRequestException('Mật khẩu cũ không đúng');
        }
        // Kiểm tra mật khẩu mới có khác mật khẩu cũ không
        const isSamePassword = await compare(newPassword, user.password);
        if (isSamePassword) {
            throw new BadRequestException('Mật khẩu mới không được giống mật khẩu cũ');
        }
        const hashPassword = await this.getHashPassword(newPassword);
        await this.prisma.user.update({
            where: {
                id: user.id
            },
            data: {
                password: hashPassword
            }
        });
        return {
            id: user.id,
            email: user.email,
        };
    }

    async updateUserPassword(email: string, newPassword: string) {
        return await this.prisma.user.update({
            where: {
                email: email
            },
            data: {
                password: newPassword
            }
        });
    }
}
