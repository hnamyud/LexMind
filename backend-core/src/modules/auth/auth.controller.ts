import { BadRequestException, Body, Controller, Get, Post, Req, Res, UseGuards } from '@nestjs/common';
import type { Request, Response } from 'express';
import { AuthService } from './auth.service';
import { ConfigService } from '@nestjs/config';
import { GetUser, Public, ResponseMessage } from 'src/core/decorators/customize.decorator';
import { LocalAuthGuard } from 'src/common/guards/local-auth.guard';
import { ApiBearerAuth, ApiBody, ApiProperty } from '@nestjs/swagger';
import { LoginDto } from './dto/login.dto';
import { RegisterUserDto } from '../users/dto/create-user.dto';
import { GoogleAuthGuard } from 'src/common/guards/google-auth.guard';
import { ResetPasswordDto, VerifyOtpDto } from './dto/reset-password.dto';
import { ChangePasswordDto } from './dto/change-password.dto';
import type { IUser } from 'src/common/interfaces/users.interface';
import { Ability } from '@casl/ability';
import { CheckPolicies } from 'src/core/decorators/policy.decorator';
import { Action } from 'src/common/enum/action.enum';
import { Throttle } from '@nestjs/throttler';

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
  @ResponseMessage('Đăng nhập thành công!')
  @ApiBody({
    type: LoginDto,
    description: 'Thông tin đăng nhập',
    examples: {
      default: {
        summary: 'Đăng nhập',
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
  @ResponseMessage("Đăng xuất thành công!")
  handleLogout(
    @Req() req: Request & { user: any },
    @Res({ passthrough: true }) response: Response
  ) {
    return this.authService.logout(req.user, response);
  }

  @Post('/register')
  @Public()
  @ResponseMessage('Đăng ký thành công!')
  @ApiBody({ type: RegisterUserDto })
  async handleRegister(
    @Body() RegisterUserDto: RegisterUserDto
  ) {
    return await this.authService.register(RegisterUserDto);
  }

  @Get('/google/login')
  @Public()
  @UseGuards(GoogleAuthGuard)
  @ResponseMessage("Đăng nhập bằng Google")
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

  @Get('/profile')
  @CheckPolicies({
    handle: (ability: Ability) => ability.can(Action.Read, 'User'),
    message: 'Bạn không có quyền đọc thông tin user!'
  })
  @ApiBearerAuth('access-token')
  @ResponseMessage("Lấy thông tin user thành công!")
  async getProfile(@GetUser() user: IUser) {
    return await this.authService.getUserInfo(user);
  }

  @Post('/verify-otp')
  @Public()
  @Throttle({ short: { ttl: 60000, limit: 3 } }) 
  @ResponseMessage("Xác thực OTP thành công!")
  @ApiBody({ type: VerifyOtpDto })
  async verifyOtp(@Body() verifyOtpDto: VerifyOtpDto) {
    const isValid = await this.authService.verifyOtp(verifyOtpDto.email, verifyOtpDto.otp);
    if (!isValid) throw new BadRequestException('OTP không hợp lệ hoặc đã hết hạn!');
    return { message: 'Xác thực OTP thành công!' };
  }

  @Post('/reset-password')
  @Public()
  @Throttle({ short: { ttl: 60000, limit: 3 } }) 
  @ResponseMessage("Đặt lại mật khẩu thành công!")
  @ApiBody({ type: ResetPasswordDto })
  async handleResetPassword(
    @Body() resetPasswordDto: ResetPasswordDto
  ) {
    return await this.authService.resetPassword(resetPasswordDto);
  }

  @Post('/change-password')
  @ApiBearerAuth('access-token')
  @ResponseMessage("Thay đổi mật khẩu thành công!")
  @ApiBody({ type: ChangePasswordDto })
  async handleChangePassword(
    @GetUser() user: IUser,
    @Body() changePasswordDto: ChangePasswordDto
  ) {
    return await this.authService.changePassword(user.id, changePasswordDto);
  }
}
