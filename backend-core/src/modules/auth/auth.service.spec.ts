import { Test, TestingModule } from '@nestjs/testing';
import { AuthService } from './auth.service';
import { JwtService } from '@nestjs/jwt';
import { ConfigService } from '@nestjs/config';
import { UsersService } from 'src/modules/users/users.service';
import { PrismaService } from 'prisma/prisma.service';

describe('AuthService', () => {
    let service: AuthService;

    const mockJwtService = {
        sign: jest.fn(),
        verify: jest.fn()
    };

    const mockConfigService = {
        get: jest.fn()
    }

    const mockUsersService = {
        findOneByEmail: jest.fn(),
        isValidPassword: jest.fn(),
        queryUserByToken: jest.fn(),
        updateUserToken: jest.fn(),
        registerUser: jest.fn(),
        getHashPassword: jest.fn(),
        updateUserPassword: jest.fn(),
    }

    const mockPrismaService = {
        user: {
            update: jest.fn(),
        }
    }

    const mockRedisClient = {
        get: jest.fn(),
        set: jest.fn(),
        del: jest.fn(),
        incr: jest.fn(),
        expire: jest.fn()
    }

    beforeEach(async () => {
        const module: TestingModule = await Test.createTestingModule({
            providers: [
                AuthService,
                { provide: JwtService, useValue: mockJwtService },
                { provide: ConfigService, useValue: mockConfigService },
                { provide: UsersService, useValue: mockUsersService },
                { provide: PrismaService, useValue: mockPrismaService },
                { provide: 'REDIS_CLIENT', useValue: mockRedisClient },
            ],
        }).compile();

        service = module.get<AuthService>(AuthService);
    });

    afterEach(() => {
        jest.clearAllMocks();
    });

    it('should be defined', () => {
        expect(service).toBeDefined();
    });
});
