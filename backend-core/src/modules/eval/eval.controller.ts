import { Controller, Post, Get, Body, Param, Query } from '@nestjs/common';
import { EvalService } from './eval.service';
import { RunBatchDto } from './dto/run-batch.dto';

@Controller('eval')
export class EvalController {
  constructor(private readonly evalService: EvalService) {}

  @Get('datasets')
  async getDatasets() {
    return this.evalService.getDatasets();
  }

  @Post('run-batch')
  async runBatch(@Body() runBatchDto: RunBatchDto) {
    return this.evalService.runBatch(runBatchDto);
  }

  @Get('sessions')
  async getSessions(@Query('limit') limit?: number) {
    return this.evalService.getSessions(limit || 20);
  }

  @Get('results/:sessionId')
  async getResults(@Param('sessionId') sessionId: string) {
    return this.evalService.getResults(sessionId);
  }

  @Get('stats/:sessionId')
  async getStats(@Param('sessionId') sessionId: string) {
    return this.evalService.getStats(sessionId);
  }

}
