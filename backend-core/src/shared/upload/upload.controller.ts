import { Controller, Delete, Param, Post, UploadedFiles, UseGuards, UseInterceptors } from '@nestjs/common';
import { FilesInterceptor } from '@nestjs/platform-express';
import { ApiBearerAuth, ApiBody, ApiConsumes, ApiTags } from '@nestjs/swagger';
import { CloudinaryService } from './cloudinary.service';
import { ImagesUploadDto } from './dto/image-upload.dto';
import { PoliciesGuard } from 'src/common/guards/policy.guard';
import { ResponseMessage } from 'src/core/decorators/customize.decorator';

@ApiTags('Upload')
@Controller('upload')
@UseGuards(PoliciesGuard)
export class UploadController {
  constructor(private readonly cloudinaryService: CloudinaryService) {}

  @Post()
  @ApiBearerAuth('access-token')
  @ApiConsumes('multipart/form-data')
  @ApiBody({
    description: 'Upload images',
    type: ImagesUploadDto,
  })
  @UseInterceptors(FilesInterceptor('images', 2)) // Tối đa 2 file
  async uploadImages(@UploadedFiles() files: Express.Multer.File[]) {
    const uploadPromises = files.map(file => this.cloudinaryService.uploadFile(file));
    const uploadResults = await Promise.all(uploadPromises);

    return uploadResults.map(result => ({
      url: result.secure_url,
      public_id: result.public_id,
    }));
  }

  @Delete(':publicId')
  @ApiBearerAuth('access-token')
  @ResponseMessage ("Delete image from Cloudinary")
  async deleteImage(@Param('publicId') publicId: string) {
    return await this.cloudinaryService.deleteImage(publicId);
  }
}