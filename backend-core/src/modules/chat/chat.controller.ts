import { Controller, Post, Body, Res, UseGuards, Param, Get, Query } from '@nestjs/common';
import { ChatService } from './chat.service';
import { ApiBearerAuth, ApiBody, ApiTags } from '@nestjs/swagger';
import type { Response } from 'express';
import { ResponseMessage } from 'src/core/decorators/customize.decorator';
import { ConversationOwnerGuard } from 'src/common/guards/conversation-owner.guard';
import { QuestionDto } from './dto/question.dto';
import { Throttle } from '@nestjs/throttler';

@ApiTags('Chat')
@Controller('chat')
export class ChatController {
  constructor(private readonly chatService: ChatService) { }

  @Post('/ask/stream')
  @ApiBearerAuth('access-token')
  @ResponseMessage('Ask AI')
  @Throttle({ short: { ttl: 60000, limit: 5 } })
  @UseGuards(ConversationOwnerGuard)
  @ApiBody({
    type: QuestionDto,
    description: "Ask",
    examples: {
      default: {
        value: {
          question: "Vượt đèn đỏ bị phạt bao nhiêu tiền?",
          conversationId: "123e4567-e89b-12d3-a456-426614174000",
          image: {
            url: "https://res.cloudinary.com/demo/image/upload/v1710000000/violation.jpg",
            public_id: "demo/violation"
          }
        }
      }
    }
  })
  async askAI(
    @Body() questionDto: QuestionDto,
    @Res() res: Response) {
    await this.chatService.askAI(
      questionDto.question,
      questionDto.conversationId as string,
      res,
    );
  }

  @Post('/regenerate/:messageId')
  @ApiBearerAuth('access-token')
  @ResponseMessage('Regenerate AI Answer')
  @Throttle({ default: { ttl: 60000, limit: 5 } })
  // @UseGuards(ConversationOwnerGuard) -> Tạm ẩn vì Guard này đang check Body.conversationId, nếu muốn dùng phải thiết kế Auth lại
  async regenerate(
    @Param('messageId') messageId: string,
    @Res() res: Response
  ) {
    await this.chatService.regenerateMessage(messageId, res);
  }

  @Get('/law-detail/:nodeId')
  @Throttle({ default: { ttl: 60000, limit: 30 } })
  @ApiBearerAuth('access-token')
  @ResponseMessage('Get Law Detail')
  async getLawDetail(
    @Param('nodeId') nodeId: string,
    @Query('limit') limit?: string,
  ) {
    return this.chatService.getLawDetail(nodeId, limit);
  }
}
