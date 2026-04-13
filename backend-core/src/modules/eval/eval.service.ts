import { Injectable, InternalServerErrorException, HttpException } from '@nestjs/common';
import { HttpService } from '@nestjs/axios';
import { ConfigService } from '@nestjs/config';
import { catchError, firstValueFrom } from 'rxjs';
import { RunBatchDto } from './dto/run-batch.dto';

@Injectable()
export class EvalService {
  private readonly aiServiceUrl: string;
  private readonly internalSecret: string;

  constructor(
    private readonly httpService: HttpService,
    private readonly configService: ConfigService,
  ) {
    const port = this.configService.get<string>('FASTAPI_PORT') || '8001';
    const host = this.configService.get<string>('FASTAPI_URL') || '127.0.0.1';
    this.aiServiceUrl = `http://${host}:${port}`;
    this.internalSecret = this.configService.get<string>('INTERNAL_SECRET') || '';
  }

  private get headers() {
    return {
      'Content-Type': 'application/json',
      'INTERNAL-SECRET': this.internalSecret,
    };
  }

  async getDatasets() {
    const url = `${this.aiServiceUrl}/eval/datasets`;
    const { data } = await firstValueFrom(
      this.httpService.get(url, { headers: this.headers }).pipe(
        catchError((error) => {
          throw new HttpException(
            error.response?.data || 'AI Service Error',
            error.response?.status || 500,
          );
        }),
      ),
    );
    return data;
  }

  async runBatch(dto: RunBatchDto) {
    const url = `${this.aiServiceUrl}/eval/run-batch`;
    const { data } = await firstValueFrom(
      this.httpService.post(url, dto, { headers: this.headers }).pipe(
        catchError((error) => {
          throw new HttpException(
            error.response?.data || 'AI Service Error',
            error.response?.status || 500,
          );
        }),
      ),
    );
    return data;
  }

  async getSessions(limit: number = 20) {
    const url = `${this.aiServiceUrl}/eval/sessions?limit=${limit}`;
    const { data } = await firstValueFrom(
      this.httpService.get(url, { headers: this.headers }).pipe(
        catchError((error) => {
          throw new HttpException(
            error.response?.data || 'AI Service Error',
            error.response?.status || 500,
          );
        }),
      ),
    );
    return data;
  }

  async getResults(sessionId: string) {
    const url = `${this.aiServiceUrl}/eval/results/${sessionId}`;
    const { data } = await firstValueFrom(
      this.httpService.get(url, { headers: this.headers }).pipe(
        catchError((error) => {
          throw new HttpException(
            error.response?.data || 'AI Service Error',
            error.response?.status || 500,
          );
        }),
      ),
    );
    return data;
  }

  async getStats(sessionId: string) {
    const url = `${this.aiServiceUrl}/eval/stats/${sessionId}`;
    const { data } = await firstValueFrom(
      this.httpService.get(url, { headers: this.headers }).pipe(
        catchError((error) => {
          throw new HttpException(
            error.response?.data || 'AI Service Error',
            error.response?.status || 500,
          );
        }),
      ),
    );
    return data;
  }
}
