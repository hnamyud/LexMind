import { Module } from '@nestjs/common';
import { HttpModule } from '@nestjs/axios';
import { EvalController } from './eval.controller';
import { EvalService } from './eval.service';

@Module({
  imports: [HttpModule],
  controllers: [EvalController],
  providers: [EvalService],
})
export class EvalModule {}
