import { ApiProperty, ApiPropertyOptional } from "@nestjs/swagger";
import { Type } from "class-transformer";
import { IsNotEmpty, IsOptional, IsString, IsUrl, MaxLength, MinLength, ValidateNested } from "class-validator";

export class CloudinaryImageDto {
    @ApiProperty({ description: 'URL ảnh từ Cloudinary' })
    @IsString()
    @IsUrl({ require_protocol: true })
    url!: string;

    @ApiProperty({ description: 'public_id ảnh từ Cloudinary' })
    @IsString()
    @IsNotEmpty()
    public_id!: string;
}

export class QuestionDto {
    @ApiProperty()
    @IsString()
    @IsNotEmpty()
    @MinLength(2)
    @MaxLength(1000)
    question!: string;

    @ApiPropertyOptional()
    @IsString()
    @IsOptional()
    conversationId?: string;

    @ApiPropertyOptional({ type: CloudinaryImageDto })
    @ValidateNested()
    @Type(() => CloudinaryImageDto)
    @IsOptional()
    image?: CloudinaryImageDto;
}