import { Body, Controller, Param, Post, Put, UseGuards, Get } from '@nestjs/common';
import { ApiBearerAuth, ApiBody, ApiTags, ApiOperation } from '@nestjs/swagger';
import { FeedbacksService } from './feedbacks.service';
import { CreateFeedbackDto } from './dto/create-feedback.dto';
import { GetUser, ResponseMessage } from 'src/core/decorators/customize.decorator';
import type { IUser } from 'src/common/interfaces/users.interface';
import { CheckPolicies } from 'src/core/decorators/policy.decorator';
import { AppAbility } from 'src/core/casl/ability.factory';
import { Action } from 'src/common/enum/action.enum';
import { Ability } from '@casl/ability';

@ApiTags('Feedbacks')
@Controller('feedbacks')
export class FeedbacksController {
    constructor(private readonly feedbacksService: FeedbacksService) { }

    @Post('/message/:messageId')
    @ApiBearerAuth('access-token')
    @ApiOperation({ summary: 'Gửi đánh giá (thích/không thích) cho tin nhắn của AI.' })
    @ResponseMessage('Đã gửi phản hồi thành công!')
    @ApiBody({ type: CreateFeedbackDto })
    async submitFeedback(
        @Param('messageId') messageId: string,
        @Body() createFeedbackDto: CreateFeedbackDto,
        @GetUser() user: IUser,
    ) {
        // Gọi upsert: Nếu user chưa vote, tự chèn vào. Đã vote thì update.
        return this.feedbacksService.upsertFeedback(messageId, user, createFeedbackDto);
    }

    @Get('/message/:messageId')
    @ApiBearerAuth('access-token')
    @CheckPolicies({
        // Chỉ admin mới được phép truy xuất danh sách feedback
        handle: (ability: Ability) => ability.can(Action.Manage, 'all')
    })
    @ApiOperation({ summary: 'Xem tất cả những bài đánh giá về tin nhắn (Dành cho Admin).' })
    @ResponseMessage('Truy xuất danh sách phản hồi thành công!')
    async getFeedbacks(@Param('messageId') messageId: string) {
        return this.feedbacksService.fetchFeedbacksByMessage(messageId);
    }
}
