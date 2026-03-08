import { Body, Controller, Delete, Get, Param, Put, Query } from '@nestjs/common';
import { ConversationsService } from './conversations.service';
import { ApiBearerAuth, ApiBody } from '@nestjs/swagger';
import { GetUser, ResponseMessage } from 'src/core/decorators/customize.decorator';
import type { IUser } from 'src/common/interfaces/users.interface';
import { UpdateConversationDto } from './dto/update-conversation.dto';
import { Ability } from '@casl/ability';
import { Action } from 'src/common/enum/action.enum';
import { CheckPolicies } from 'src/core/decorators/policy.decorator';
@Controller('conversations')
export class ConversationsController {
  constructor(private readonly conversationsService: ConversationsService) { }

  @Get('/')
  @CheckPolicies({
    handle: (ability: Ability) => ability.can(Action.Read, 'Conversation')
  })
  @ApiBearerAuth('access-token')
  @ResponseMessage('Lấy danh sách cuộc trò chuyện thành công!')
  async getAllConversations(
    @Query('current') currentPage: string,
    @Query('pageSize') limit: string,
    @GetUser() user: IUser
  ) {
    return this.conversationsService.findAll(+currentPage || 1, +limit || 10, user);
  }

  @Put('/:id')
  @ApiBearerAuth('access-token')
  @ResponseMessage('Cập nhật thông tin cuộc trò chuyện thành công!')
  @ApiBody({ type: UpdateConversationDto })
  async updateConversation(
    @Param('id') id: string,
    @Body() updateConversationDto: UpdateConversationDto,
    @GetUser() user: IUser
  ) {
    await this.conversationsService.getConversationById(id, user);
    return this.conversationsService.updateConversation(
      id,
      updateConversationDto.title,
      updateConversationDto.summary
    );
  }

  @Delete('/:id')
  @ApiBearerAuth('access-token')
  @CheckPolicies({
    handle: (ability: Ability) => ability.can(Action.Delete, 'Conversation')
  })
  @ResponseMessage('Xóa cuộc trò chuyện thành công!')
  async deleteConversation(
    @Param('id') id: string,
    @GetUser() user: IUser
  ) {
    await this.conversationsService.getConversationById(id, user);
    return this.conversationsService.softDeleteConversation(id);
  }
}
