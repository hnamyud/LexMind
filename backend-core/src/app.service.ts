import { HttpService } from '@nestjs/axios';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';

@Injectable()
export class AppService {
  private readonly logger = new Logger(AppService.name);
  constructor(
      private readonly httpService: HttpService,
      private readonly configService: ConfigService,
    ) { }

  async getGraphDemo(id?: string) {
    const fastApiUrl = this.configService.get<string>('FASTAPI_URL');
    const fastApiPort = this.configService.get<string>('FASTAPI_PORT');
    const seedId = id?.trim() || 'nd168_2024_d7_k7';
    
    try {
      const response = await this.httpService.axiosRef.get(
        `http://${fastApiUrl}:${fastApiPort}/graph/demo`,
        {
          params: { id: seedId },
        },
      );
      return response.data;
    } catch (err) {
      this.logger.error(`Lỗi khi lấy dữ liệu graph demo (id=${seedId}):`, err);
      throw err;
    }
  }
}
