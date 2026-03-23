import { Controller, Get, Param, Query, UseGuards } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiQuery, ApiTags } from '@nestjs/swagger';
import { AdminService } from './admin.service';
import { GetUsersDto } from './dto/get-users.dto';
import { GetConversationsDto } from './dto/get-conversations.dto';
import { StatsQueryDto } from './dto/stats-query.dto';
import { GetFeedbacksDto } from './dto/get-feedbacks.dto';
import { CheckPolicies } from 'src/core/decorators/policy.decorator';
import { Action } from 'src/common/enum/action.enum';
import { Ability } from '@casl/ability';
import { ResponseMessage } from 'src/core/decorators/customize.decorator';

@ApiTags('Admin')
@Controller('admin')
@ApiBearerAuth('access-token')
export class AdminController {
  constructor(private readonly adminService: AdminService) {}

  // ==================== USER MANAGEMENT ====================

  @Get('users')
  @CheckPolicies({ handle: (ability: Ability) => ability.can(Action.Manage, 'all') })
  @ApiOperation({ summary: 'Lấy danh sách users với thống kê (Admin only)' })
  @ResponseMessage('Lấy danh sách users thành công')
  async getUsers(@Query() query: GetUsersDto) {
    return this.adminService.getUsers(query);
  }

  @Get('users/:userId')
  @CheckPolicies({ handle: (ability: Ability) => ability.can(Action.Manage, 'all') })
  @ApiOperation({ summary: 'Lấy chi tiết user với hoạt động gần đây (Admin only)' })
  @ResponseMessage('Lấy chi tiết user thành công')
  async getUserDetail(@Param('userId') userId: string) {
    return this.adminService.getUserDetail(userId);
  }

  // ==================== CONVERSATION MANAGEMENT ====================

  @Get('conversations')
  @CheckPolicies({ handle: (ability: Ability) => ability.can(Action.Manage, 'all') })
  @ApiOperation({ summary: 'Lấy tất cả conversations của mọi user (Admin only)' })
  @ResponseMessage('Lấy danh sách conversations thành công')
  async getConversations(@Query() query: GetConversationsDto) {
    return this.adminService.getConversations(query);
  }

  @Get('conversations/stats')
  @CheckPolicies({ handle: (ability: Ability) => ability.can(Action.Manage, 'all') })
  @ApiOperation({ summary: 'Thống kê conversations (Admin only)' })
  @ResponseMessage('Lấy thống kê conversations thành công')
  async getConversationStats(@Query() query: StatsQueryDto) {
    return this.adminService.getConversationStats(query);
  }

  @Get('conversations/:conversationId')
  @CheckPolicies({ handle: (ability: Ability) => ability.can(Action.Manage, 'all') })
  @ApiOperation({ summary: 'Lấy chi tiết conversation với tất cả messages (Admin only)' })
  @ResponseMessage('Lấy chi tiết conversation thành công')
  async getConversationDetail(@Param('conversationId') conversationId: string) {
    return this.adminService.getConversationDetail(conversationId);
  }

  // ==================== AI PERFORMANCE ====================

  @Get('ai/performance')
  @CheckPolicies({ handle: (ability: Ability) => ability.can(Action.Manage, 'all') })
  @ApiOperation({ summary: 'Metrics hiệu suất AI (response time, tokens, cost)' })
  @ResponseMessage('Lấy metrics hiệu suất AI thành công')
  async getAIPerformance(@Query() query: StatsQueryDto) {
    return this.adminService.getAIPerformance(query);
  }

  @Get('ai/quality')
  @CheckPolicies({ handle: (ability: Ability) => ability.can(Action.Manage, 'all') })
  @ApiOperation({ summary: 'Metrics chất lượng AI (dựa trên feedback)' })
  @ResponseMessage('Lấy metrics chất lượng AI thành công')
  async getAIQuality(@Query() query: StatsQueryDto) {
    return this.adminService.getAIQuality(query);
  }

  @Get('ai/cache')
  @CheckPolicies({ handle: (ability: Ability) => ability.can(Action.Manage, 'all') })
  @ApiOperation({ summary: 'Cache analytics: hit rate, response time comparison, time saved' })
  @ResponseMessage('Lấy cache analytics thành công')
  async getCacheAnalytics(@Query() query: StatsQueryDto) {
    return this.adminService.getCacheAnalytics(query);
  }

  // ==================== PHASE 3: HEALTH CHECK ====================

  @Get('health')
  @CheckPolicies({ handle: (ability: Ability) => ability.can(Action.Manage, 'all') })
  @ApiOperation({ summary: 'Kiểm tra trạng thái các service (database, AI, Redis)' })
  @ResponseMessage('Kiểm tra sức khỏe hệ thống thành công')
  async getHealthCheck() {
    return this.adminService.getHealthCheck();
  }

  // ==================== PHASE 3: ENHANCED SYSTEM STATS ====================

  @Get('system/stats')
  @CheckPolicies({ handle: (ability: Ability) => ability.can(Action.Manage, 'all') })
  @ApiOperation({ summary: 'Thống kê hệ thống chi tiết (active users, error rate, performance)' })
  @ResponseMessage('Lấy thống kê hệ thống thành công')
  async getSystemStats() {
    return this.adminService.getEnhancedSystemStats();
  }

  // ==================== PHASE 3: ENHANCED FEEDBACKS ====================

  @Get('feedbacks')
  @CheckPolicies({ handle: (ability: Ability) => ability.can(Action.Manage, 'all') })
  @ApiOperation({ summary: 'Lấy danh sách feedbacks với filter và pagination (Admin only)' })
  @ResponseMessage('Lấy danh sách feedbacks thành công')
  async getFeedbacks(@Query() query: GetFeedbacksDto) {
    return this.adminService.getFeedbacks(query);
  }

  @Get('feedbacks/analytics')
  @CheckPolicies({ handle: (ability: Ability) => ability.can(Action.Manage, 'all') })
  @ApiOperation({ summary: 'Phân tích chi tiết feedbacks (trends, correlation với response time)' })
  @ResponseMessage('Lấy phân tích feedbacks thành công')
  async getFeedbackAnalytics(@Query() query: StatsQueryDto) {
    return this.adminService.getFeedbackAnalytics(query);
  }

  // ==================== PHASE 3: AI ERRORS ====================

  @Get('ai/errors')
  @CheckPolicies({ handle: (ability: Ability) => ability.can(Action.Manage, 'all') })
  @ApiOperation({ summary: 'Danh sách lỗi AI với chi tiết (Admin only)' })
  @ResponseMessage('Lấy danh sách lỗi AI thành công')
  async getAIErrors(@Query() query: GetFeedbacksDto) {
    return this.adminService.getAIErrors(query);
  }
}
