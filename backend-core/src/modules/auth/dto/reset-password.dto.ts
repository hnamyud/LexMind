import { ApiProperty } from '@nestjs/swagger';
import { IsEmail, IsNotEmpty, IsNumberString, MaxLength, MinLength } from 'class-validator';

export class SendResetPasswordDto {
  @ApiProperty()
  @IsEmail({}, { message: 'Email không hợp lệ' })
  @IsNotEmpty({ message: 'Email không được để trống' })
  email: string;
}

export class VerifyOtpDto {
  @ApiProperty()
  @IsEmail({}, { message: 'Email không đúng định dạng' })
  @IsNotEmpty()
  email: string;

  @ApiProperty()
  @MinLength(6, { message: 'OTP phải có ít nhất 6 ký tự' })
  @MaxLength(6, { message: 'OTP không được vượt quá 6 ký tự' })
  @IsNotEmpty({ message: 'OTP không được để trống' })
  @IsNumberString()
  otp: string;
}

export class ResetPasswordDto {
  @ApiProperty()
  @IsEmail({}, { message: 'Email không đúng định dạng' })
  @IsNotEmpty()
  email: string;

  @ApiProperty()
  @MinLength(6, { message: 'OTP phải có ít nhất 6 ký tự' })
  @MaxLength(6, { message: 'OTP không được vượt quá 6 ký tự' }) 
  @IsNotEmpty({ message: 'OTP không được để trống' })
  @IsNumberString()
  otp: string;

  @ApiProperty()
  @IsNotEmpty({ message: 'Mật khẩu mới không được để trống' })
  @MinLength(8, { message: 'Mật khẩu phải có ít nhất 8 ký tự' })
  newPassword: string;
}