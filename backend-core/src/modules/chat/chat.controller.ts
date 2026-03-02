import { Controller, Post, Body, Res, UseGuards } from '@nestjs/common';
import { ChatService } from './chat.service';
import { ApiBearerAuth, ApiBody, ApiTags } from '@nestjs/swagger';
import type { Response } from 'express';
import { ResponseMessage } from 'src/core/decorators/customize.decorator';
import { ConversationOwnerGuard } from 'src/common/guards/conversation-owner.guard';
import { QuestionDto } from './dto/question.dto';

@ApiTags('Chat')
@Controller('chat')
export class ChatController {
  constructor(private readonly chatService: ChatService) { }

  @Post('/ask/stream')
  @ApiBearerAuth('access-token')
  @ResponseMessage('Ask AI')
  @UseGuards(ConversationOwnerGuard)
  @ApiBody({ type: QuestionDto })
  async askAI(
    @Body() questionDto: QuestionDto,
    @Res() res: Response) {
    await this.chatService.askAI(questionDto.question, questionDto.conversationId as string, res);
  }
}
