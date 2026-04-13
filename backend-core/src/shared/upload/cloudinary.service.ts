import { Injectable } from '@nestjs/common';
import { v2, UploadApiErrorResponse, UploadApiResponse } from 'cloudinary';
import { CloudinaryResponse } from './cloudinary-response';
import { Readable } from 'stream';
import sharp = require('sharp');

@Injectable()
export class CloudinaryService {
  uploadFile(file: Express.Multer.File): Promise<UploadApiResponse | UploadApiErrorResponse> {
    return new Promise((resolve, reject) => {
      const upload = v2.uploader.upload_stream(
        {
          folder: 'lex-mind',
          resource_type: 'image',
        },
        (error, result) => {
          if (error) return reject(error);
          if (!result) return reject(new Error('Unknown error: result is undefined'));
          resolve(result);
        });

      const sharpStream = sharp()
        .resize(2000, 2000, {
          fit: 'inside',
          withoutEnlargement: true, // Only scale down if it is larger than 2000px
        })
        .webp({ quality: 90, smartSubsample: true }); // smartSubsample is highly effective to keep edges sharp

      sharpStream.on('error', (err) => reject(err));

      const stream = new Readable();
      stream.push(file.buffer);
      stream.push(null);
      stream.pipe(sharpStream).pipe(upload);
    });
  }

  async deleteImage(publicId: string): Promise<any> {
    return new Promise((resolve, reject) => {
      v2.uploader.destroy(publicId, (error, result) => {
        if (error) return reject(error);
        resolve(result);
      });
    });
  }
}