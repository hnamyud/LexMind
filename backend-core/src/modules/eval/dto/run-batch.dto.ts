import { IsOptional, IsString, IsInt, IsBoolean, Min, Max, IsArray } from 'class-validator';

export class RunBatchDto {
  @IsOptional()
  @IsString()
  dataset?: string;

  @IsOptional()
  @IsString()
  source_doc?: string;

  @IsOptional()
  @IsInt()
  @Min(1)
  @Max(10)
  concurrency?: number;  // Default trên API là 1 — an toàn nhất cho eval

  @IsOptional()
  @IsInt()
  @Min(1)
  limit?: number;

  @IsOptional()
  @IsBoolean()
  random_sample?: boolean;  // true = bốc ngẫu nhiên; false = lấy tuần tự từ đầu

  @IsOptional()
  @IsInt()
  @Min(0)
  offset?: number;  // Chỉ có tác dụng khi random_sample=false

  @IsOptional()
  @IsArray()
  @IsString({ each: true })
  question_ids?: string[];
}
