import { IsBoolean, IsNotEmpty, IsOptional, IsString } from 'class-validator';
import { ApiProperty } from '@nestjs/swagger';

export class CreateFeedbackDto {
    @IsNotEmpty({ message: 'isLike không được để trống' })
    @IsBoolean({ message: 'isLike phải là một giá trị boolean (true/false)' })
    @ApiProperty({
        description: 'Đánh giá tin nhắn của AI (true: Thích, false: Không thích)',
        example: false,
    })
    isLike: boolean;

    @IsOptional()
    @IsString({ message: 'lý do phải là một chuỗi văn bản' })
    @ApiProperty({
        description: 'Lý do cho việc không thích (tuỳ chọn)',
        example: 'AI trả lời không đúng bối cảnh pháp lý của Việt Nam.',
        required: false,
    })
    reason?: string;
}
