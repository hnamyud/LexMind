import { ApiProperty } from "@nestjs/swagger";
import { IsNotEmpty, IsOptional, IsString, MaxLength, MinLength } from "class-validator";

export class QuestionDto {
    @ApiProperty()
    @IsString()
    @IsNotEmpty()
    @MinLength(2)
    @MaxLength(1000)
    question: string;

    @ApiProperty({ required: false })
    @IsString()
    @IsOptional()
    conversationId: string;
}