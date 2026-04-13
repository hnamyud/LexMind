import { Module } from '@nestjs/common';
import { CloudinaryProvider } from './cloudinary.provider';
import { CaslModule } from 'src/core/casl/casl.module';
import { CloudinaryService } from './cloudinary.service';
import { UploadController } from './upload.controller';


@Module({
  imports: [CaslModule],
  providers: [CloudinaryProvider, CloudinaryService],
  exports: [CloudinaryProvider, CloudinaryService],
  controllers: [UploadController],
})
export class CloudinaryModule {}