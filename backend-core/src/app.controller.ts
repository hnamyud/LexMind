import { Controller, Get, Query } from '@nestjs/common';
import { AppService } from './app.service';
import { Throttle } from '@nestjs/throttler';
import { ApiBearerAuth } from '@nestjs/swagger';
import { Public, ResponseMessage } from './core/decorators/customize.decorator';

@Controller()
export class AppController {
  constructor(private readonly appService: AppService) { }

  @Get('/graph/demo')
  @Public()
  @Throttle({ default: { ttl: 60000, limit: 30 } })
  @ResponseMessage('Get Graph Demo Data')
  async getGraphDemo(@Query('id') id?: string) {
    return this.appService.getGraphDemo(id);
  }
}
