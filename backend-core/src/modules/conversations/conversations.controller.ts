import { Body, Controller, Get, Param, Put, Query } from '@nestjs/common';
import { ConversationsService } from './conversations.service';
import { ApiBearerAuth, ApiBody } from '@nestjs/swagger';
import { GetUser, ResponseMessage } from 'src/core/decorators/customize.decorator';
import type { IUser } from 'src/common/interfaces/users.interface';
import { UpdateConversationDto } from './dto/update-conversation.dto';
@Controller('conversations')
export class ConversationsController {
  constructor(private readonly conversationsService: ConversationsService) { }

  @Get('/')
  @ApiBearerAuth('access-token')
  @ResponseMessage('Get all conversations')
  async getAllConversations(
    @Query('current') currentPage: string,
    @Query('pageSize') limit: string,
    @GetUser() user: IUser
  ) {
    return this.conversationsService.findAll(+currentPage || 1, +limit || 10, user);
  }

  @Get('/:id')
  @ApiBearerAuth('access-token')
  @ResponseMessage('Get conversation by id')
  async getConversationById(
    @Param('id') id: string,
    @GetUser() user: IUser
  ) {
    return this.conversationsService.getConversationById(id, user);
  }

  @Put('/:id')
  @ApiBearerAuth('access-token')
  @ResponseMessage('Update conversation info')
  @ApiBody({ type: UpdateConversationDto })
  async updateConversation(
    @Param('id') id: string,
    @Body() updateConversationDto: UpdateConversationDto
  ) {
    return this.conversationsService.updateConversation(
      id,
      updateConversationDto.title,
      updateConversationDto.summary
    );
  }
}
