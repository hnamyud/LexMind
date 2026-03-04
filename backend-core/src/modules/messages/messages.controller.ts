import { Controller, Get, Param, Query } from '@nestjs/common';
import { MessagesService } from './messages.service';
import { ApiBearerAuth } from '@nestjs/swagger';
import { GetUser, ResponseMessage } from 'src/core/decorators/customize.decorator';
import type { IUser } from 'src/common/interfaces/users.interface';

@Controller('messages')
export class MessagesController {
  constructor(private readonly messagesService: MessagesService) { }

  @Get('/')
  @ApiBearerAuth('access-token')
  @ResponseMessage('Get messages by conversation id')
  async getAllMessageById(
    @Query('conversationId') conversationId: string,
    @Query('current') currentPage: string,
    @Query('pageSize') limit: string,
    @GetUser() user: IUser
  ) {
    return this.messagesService.findAll(+currentPage || 1, +limit || 10, conversationId, user);
  }
}
