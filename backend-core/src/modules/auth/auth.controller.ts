import { Body, Controller, Post, Req, Res, UseGuards } from '@nestjs/common';
import type { Request, Response } from 'express';
import { AuthService } from './auth.service';
import { ConfigService } from '@nestjs/config';
import { Public, ResponseMessage } from 'src/core/decorators/customize.decorator';
import { LocalAuthGuard } from 'src/common/guards/local-auth.guard';
import { ApiBody, ApiProperty } from '@nestjs/swagger';
import { LoginDto } from './dto/login.dto';
import { RegisterUserDto } from '../users/dto/create-user.dto';

@Controller('auth')
export class AuthController {
  constructor(
    private readonly authService: AuthService,
    // private userService: UserService,
    private configService: ConfigService
  ) { }

  @Post('/login')
  @Public()
  @UseGuards(LocalAuthGuard)
  @ResponseMessage('Login success')
  @ApiBody({
    type: LoginDto,
    description: 'User login credentials',
    examples: {
      default: {
        summary: 'Login',
        value: {
          email: 'admin@gmail.com',
          password: '123456'
        }
      }
    }
  })
  async handleLogin(
    @Req() req: Request & { user: any },
    @Res({ passthrough: true }) response: Response
  ) {
    return await this.authService.login(req.user, response);
  }

  @Post('/register')
  @Public()
  @ResponseMessage('Register success')
  @ApiBody({ type: RegisterUserDto })
  async handleRegister(
    @Body() RegisterUserDto: RegisterUserDto
  ) {
    return await this.authService.register(RegisterUserDto);
  }
}
