import { ApiProperty } from '@nestjs/swagger';
import { IsNotEmpty, IsOptional, IsString } from 'class-validator';

export class UpdateConversationDto {
    @ApiProperty({ description: 'Tiêu đề của cuộc hội thoại', required: true })
    @IsNotEmpty({ message: 'Tiêu đề không được bỏ trống' })
    @IsString({ message: 'Tiêu đề phải là chuỗi' })
    title: string;

    @ApiProperty({ description: 'Tóm tắt nội dung cuộc hội thoại', required: false })
    @IsOptional()
    @IsString({ message: 'Tóm tắt phải là chuỗi' })
    summary?: string;
}
