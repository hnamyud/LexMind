import { ApiProperty, ApiPropertyOptional } from "@nestjs/swagger";
import { IsNotEmpty, IsOptional, IsString, MaxLength, MinLength } from "class-validator";
import { Transform } from "class-transformer";

function normalizeInput(value: string): string {
  return value
    ?.normalize("NFKC")
    .replace(/[\u200B-\u200D\uFEFF]/g, "") // remove zero-width
    .replace(/[\u0000-\u001F\u007F]/g, "") // remove control chars
    .trim();
}

export class QuestionDto {
    @ApiProperty()
    @IsString()
    @IsNotEmpty()
    @MinLength(2)
    @MaxLength(1000)
    @Transform(({ value }) => normalizeInput(value))
    question!: string;

    @ApiPropertyOptional()
    @IsString()
    @IsOptional()
    conversationId?: string;
}