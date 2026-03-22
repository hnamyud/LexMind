import { IsOptional, IsDateString, IsEnum } from 'class-validator';
import { ApiPropertyOptional } from '@nestjs/swagger';

export class StatsQueryDto {
  @ApiPropertyOptional({ description: 'Date from (ISO 8601)', example: '2026-03-01T00:00:00Z' })
  @IsOptional()
  @IsDateString()
  dateFrom?: string;

  @ApiPropertyOptional({ description: 'Date to (ISO 8601)', example: '2026-03-22T23:59:59Z' })
  @IsOptional()
  @IsDateString()
  dateTo?: string;

  @ApiPropertyOptional({ enum: ['hour', 'day', 'week', 'month'], default: 'day' })
  @IsOptional()
  @IsEnum(['hour', 'day', 'week', 'month'])
  groupBy?: string = 'day';

  @ApiPropertyOptional({ description: 'Filter by model name' })
  @IsOptional()
  model?: string;
}
