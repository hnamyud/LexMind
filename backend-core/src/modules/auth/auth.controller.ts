import { BadRequestException, Body, Controller, Get, Post, Req, Res, UseGuards } from '@nestjs/common';
import type { Request, Response } from 'express';
import { AuthService } from './auth.service';
import { ConfigService } from '@nestjs/config';
import { Public, ResponseMessage } from 'src/core/decorators/customize.decorator';
import { LocalAuthGuard } from 'src/common/guards/local-auth.guard';
import { ApiBearerAuth, ApiBody, ApiProperty } from '@nestjs/swagger';
import { LoginDto } from './dto/login.dto';
import { RegisterUserDto } from '../users/dto/create-user.dto';
import { GoogleAuthGuard } from 'src/common/guards/google-auth.guard';
import { ResetPasswordDto, VerifyOtpDto } from './dto/reset-password.dto';

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

  @Post('/logout')
  @ApiBearerAuth('access-token')
  @ResponseMessage("User logout")
  handleLogout(
    @Req() req: Request & { user: any },
    @Res({ passthrough: true }) response: Response
  ) {
    return this.authService.logout(req.user, response);
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

  @Get('/google/login')
  @Public()
  @UseGuards(GoogleAuthGuard)
  @ResponseMessage("Google login")
  handleGoogleLogin() {
    // This route will redirect to Google for authentication
  }

  @Get('/google/callback')
  @Public()
  @UseGuards(GoogleAuthGuard)
  @ResponseMessage("Google callback")
  async handleGoogleCallback(
    @Req() req: Request & { user: any },
    @Res({ passthrough: true }) response: Response
  ) {
    const request = await this.authService.login(req.user, response);
    response.redirect(this.configService.get('BROWSER_REDIRECT_URI') + request.accessToken);
  }

  @Post('/verify-otp')
  @Public()
  @ResponseMessage("Verify OTP")
  async verifyOtp(@Body() verifyOtpDto: VerifyOtpDto) {
    const isValid = await this.authService.verifyOtp(verifyOtpDto.email, verifyOtpDto.otp);
    if (!isValid) throw new BadRequestException('Invalid OTP or OTP has expired!');
    return { message: 'Success!' };
  }

  @Post('/reset-password')
  @Public()
  @ResponseMessage("Reset password")
  async handleResetPassword(
    @Body() resetPasswordDto: ResetPasswordDto
  ) {
    return await this.authService.resetPassword(resetPasswordDto);
  }
}
