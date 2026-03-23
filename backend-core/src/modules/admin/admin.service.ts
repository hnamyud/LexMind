import { Injectable, Inject } from '@nestjs/common';
import { PrismaService } from 'prisma/prisma.service';
import { ConfigService } from '@nestjs/config';
import { HttpService } from '@nestjs/axios';
import { GetUsersDto } from './dto/get-users.dto';
import { GetConversationsDto } from './dto/get-conversations.dto';
import { StatsQueryDto } from './dto/stats-query.dto';
import { GetFeedbacksDto } from './dto/get-feedbacks.dto';
import {
  HealthCheckResponse,
  ServiceHealth,
  SystemStatsResponse,
  FeedbackAnalyticsResponse,
  AIErrorsResponse,
  CacheAnalyticsResponse,
} from './interfaces/admin.interface';
import Redis from 'ioredis';
import { firstValueFrom, timeout, catchError } from 'rxjs';
import { of } from 'rxjs';

@Injectable()
export class AdminService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly configService: ConfigService,
    private readonly httpService: HttpService,
    @Inject('REDIS_CLIENT') private readonly redisClient: Redis,
  ) {}

  // ==================== USER MANAGEMENT ====================

  async getUsers(query: GetUsersDto) {
    const { page = 1, limit = 20, role, search, sortBy = 'createdAt', order = 'desc', includeDeleted = false } = query;

    const where: any = {};

    // Filter by role
    if (role) {
      where.role = role;
    }

    // Search by email or fullName
    if (search) {
      where.OR = [
        { email: { contains: search, mode: 'insensitive' } },
        { fullName: { contains: search, mode: 'insensitive' } },
      ];
    }

    // Include deleted users or not
    if (!includeDeleted) {
      where.deletedAt = null;
    }

    // Sorting
    const orderBy: any = {};
    if (sortBy === 'messageCount' || sortBy === 'conversationCount') {
      // These require aggregation, handle separately
      orderBy.createdAt = order;
    } else {
      orderBy[sortBy] = order;
    }

    const [data, total] = await Promise.all([
      this.prisma.user.findMany({
        where,
        skip: (page - 1) * limit,
        take: limit,
        select: {
          id: true,
          email: true,
          fullName: true,
          role: true,
          createdAt: true,
          deletedAt: true,
          _count: {
            select: {
              conversations: true,
              feedbacks: true,
            },
          },
        },
        orderBy,
      }),
      this.prisma.user.count({ where }),
    ]);

    // Calculate last active time for each user
    const usersWithStats = await Promise.all(
      data.map(async (user) => {
        const lastMessage = await this.prisma.message.findFirst({
          where: {
            conversation: {
              userId: user.id,
            },
          },
          orderBy: {
            createdAt: 'desc',
          },
          select: {
            createdAt: true,
          },
        });

        return {
          ...user,
          stats: {
            conversationCount: user._count.conversations,
            feedbackCount: user._count.feedbacks,
            lastActiveAt: lastMessage?.createdAt || null,
          },
          _count: undefined, // Remove _count from output
        };
      })
    );

    return {
      data: usersWithStats,
      total,
      page,
      limit,
    };
  }

  async getUserDetail(userId: string) {
    const user = await this.prisma.user.findUnique({
      where: { id: userId },
      select: {
        id: true,
        email: true,
        fullName: true,
        role: true,
        createdAt: true,
        deletedAt: true,
      },
    });

    if (!user) {
      return null;
    }

    // Get detailed stats
    const [
      totalConversations,
      totalFeedbacks,
      likeFeedbacks,
      dislikeFeedbacks,
      lastMessage,
      recentConversations,
    ] = await Promise.all([
      this.prisma.conversation.count({ where: { userId } }),
      this.prisma.feedback.count({ where: { userId } }),
      this.prisma.feedback.count({ where: { userId, isLike: true } }),
      this.prisma.feedback.count({ where: { userId, isLike: false } }),
      this.prisma.message.findFirst({
        where: { conversation: { userId } },
        orderBy: { createdAt: 'desc' },
        select: { createdAt: true },
      }),
      this.prisma.conversation.findMany({
        where: { userId },
        take: 5,
        orderBy: { createdAt: 'desc' },
        select: {
          id: true,
          title: true,
          createdAt: true,
          _count: {
            select: { messages: true },
          },
        },
      }),
    ]);

    const avgMessagesPerConversation = totalConversations > 0
      ? (await this.prisma.message.count({ where: { conversation: { userId } } })) / totalConversations
      : 0;

    return {
      ...user,
      stats: {
        totalConversations,
        totalFeedbacks,
        likeFeedbacks,
        dislikeFeedbacks,
        avgMessagesPerConversation: Math.round(avgMessagesPerConversation),
        lastActiveAt: lastMessage?.createdAt || null,
      },
      recentConversations: recentConversations.map(conv => ({
        id: conv.id,
        title: conv.title,
        messageCount: conv._count.messages,
        createdAt: conv.createdAt,
      })),
    };
  }

  // ==================== CONVERSATION MANAGEMENT ====================

  async getConversations(query: GetConversationsDto) {
    const {
      page = 1,
      limit = 20,
      userId,
      dateFrom,
      dateTo,
      hasNegativeFeedback,
      sortBy = 'createdAt',
      order = 'desc',
    } = query;

    const where: any = {
      isDeleted: false,
    };

    if (userId) {
      where.userId = userId;
    }

    if (dateFrom || dateTo) {
      where.createdAt = {};
      if (dateFrom) where.createdAt.gte = new Date(dateFrom);
      if (dateTo) where.createdAt.lte = new Date(dateTo);
    }

    // Filter by negative feedback
    if (hasNegativeFeedback) {
      where.messages = {
        some: {
          feedbacks: {
            some: {
              isLike: false,
            },
          },
        },
      };
    }

    const orderBy: any = {};
    orderBy[sortBy] = order;

    const [data, total] = await Promise.all([
      this.prisma.conversation.findMany({
        where,
        skip: (page - 1) * limit,
        take: limit,
        include: {
          user: {
            select: {
              id: true,
              fullName: true,
              email: true,
            },
          },
          _count: {
            select: {
              messages: true,
            },
          },
        },
        orderBy,
      }),
      this.prisma.conversation.count({ where }),
    ]);

    // Calculate stats for each conversation
    const conversationsWithStats = await Promise.all(
      data.map(async (conv) => {
        const negativeFeedbackCount = await this.prisma.feedback.count({
          where: {
            message: {
              conversationId: conv.id,
            },
            isLike: false,
          },
        });

        // Get average response time from AI metrics
        const avgResponseTime = await this.prisma.aIMetrics.aggregate({
          where: {
            message: {
              conversationId: conv.id,
            },
          },
          _avg: {
            totalTime: true,
          },
        });

        return {
          id: conv.id,
          title: conv.title,
          userId: conv.userId,
          user: conv.user,
          messageCount: conv._count.messages,
          hasNegativeFeedback: negativeFeedbackCount > 0,
          avgResponseTime: avgResponseTime._avg.totalTime || null,
          createdAt: conv.createdAt,
          updatedAt: conv.updatedAt,
        };
      })
    );

    return {
      data: conversationsWithStats,
      total,
      page,
      limit,
    };
  }

  async getConversationDetail(conversationId: string) {
    const conversation = await this.prisma.conversation.findUnique({
      where: { id: conversationId },
      include: {
        user: {
          select: {
            id: true,
            fullName: true,
            email: true,
          },
        },
        messages: {
          include: {
            feedbacks: {
              include: {
                user: {
                  select: {
                    fullName: true,
                    email: true,
                  },
                },
              },
            },
            aiMetrics: true,
          },
          orderBy: {
            createdAt: 'asc',
          },
        },
      },
    });

    if (!conversation) {
      return null;
    }

    // Calculate conversation stats
    const botMessages = conversation.messages.filter(m => m.sender === 'bot');
    const avgResponseTime = botMessages.reduce((sum, m) => sum + (m.aiMetrics?.totalTime || 0), 0) / botMessages.length || 0;
    const totalCost = botMessages.reduce((sum, m) => sum + (m.aiMetrics?.cost || 0), 0);
    const feedbackCount = conversation.messages.reduce((sum, m) => sum + m.feedbacks.length, 0);
    const likeFeedbacks = conversation.messages.reduce((sum, m) =>
      sum + m.feedbacks.filter(f => f.isLike).length, 0
    );
    const dislikeFeedbacks = conversation.messages.reduce((sum, m) =>
      sum + m.feedbacks.filter(f => !f.isLike).length, 0
    );

    return {
      id: conversation.id,
      title: conversation.title,
      userId: conversation.userId,
      user: conversation.user,
      createdAt: conversation.createdAt,
      messages: conversation.messages.map(msg => ({
        id: msg.id,
        sender: msg.sender,
        content: msg.content,
        thought: msg.thought,
        metadata: msg.metadata,
        createdAt: msg.createdAt,
        aiMetrics: msg.aiMetrics,
        feedback: msg.feedbacks[0] || null, // Assuming one feedback per message per user
      })),
      stats: {
        totalMessages: conversation.messages.length,
        avgResponseTime: Math.round(avgResponseTime),
        totalCost: Number(totalCost.toFixed(6)),
        feedbackCount,
        likeFeedbacks,
        dislikeFeedbacks,
      },
    };
  }

  async getConversationStats(query: StatsQueryDto) {
    const { dateFrom, dateTo } = query;

    const where: any = {
      isDeleted: false,
    };

    if (dateFrom || dateTo) {
      where.createdAt = {};
      if (dateFrom) where.createdAt.gte = new Date(dateFrom);
      if (dateTo) where.createdAt.lte = new Date(dateTo);
    }

    const [totalConversations, totalMessages, conversations] = await Promise.all([
      this.prisma.conversation.count({ where }),
      this.prisma.message.count({
        where: {
          conversation: where,
        },
      }),
      this.prisma.conversation.findMany({
        where,
        select: {
          userId: true,
          createdAt: true,
          _count: {
            select: {
              messages: true,
            },
          },
        },
      }),
    ]);

    const avgMessagesPerConversation = totalConversations > 0
      ? totalMessages / totalConversations
      : 0;

    // Group by date
    const conversationsPerDay = conversations.reduce((acc, conv) => {
      const date = conv.createdAt.toISOString().split('T')[0];
      acc[date] = (acc[date] || 0) + 1;
      return acc;
    }, {} as Record<string, number>);

    // Top users
    const userCounts = conversations.reduce((acc, conv) => {
      acc[conv.userId] = (acc[conv.userId] || 0) + 1;
      return acc;
    }, {} as Record<string, number>);

    const topUserIds = Object.entries(userCounts)
      .sort(([, a], [, b]) => b - a)
      .slice(0, 10)
      .map(([userId]) => userId);

    const topUsers = await Promise.all(
      topUserIds.map(async (userId) => {
        const user = await this.prisma.user.findUnique({
          where: { id: userId },
          select: { fullName: true, email: true },
        });
        return {
          userId,
          fullName: user?.fullName,
          email: user?.email,
          conversationCount: userCounts[userId],
        };
      })
    );

    return {
      totalConversations,
      totalMessages,
      avgMessagesPerConversation: Math.round(avgMessagesPerConversation),
      conversationsPerDay: Object.entries(conversationsPerDay).map(([date, count]) => ({
        date,
        count,
      })),
      topUsers,
    };
  }

  // ==================== AI PERFORMANCE ====================

  async getAIPerformance(query: StatsQueryDto) {
    const { dateFrom, dateTo, groupBy = 'day', model } = query;

    const where: any = {};

    if (dateFrom || dateTo) {
      where.createdAt = {};
      if (dateFrom) where.createdAt.gte = new Date(dateFrom);
      if (dateTo) where.createdAt.lte = new Date(dateTo);
    }

    if (model) {
      where.model = model;
    }

    // Overall metrics
    const [overview, metrics] = await Promise.all([
      this.prisma.aIMetrics.aggregate({
        where,
        _avg: {
          totalTime: true,
          ttft: true,
          cost: true,
        },
        _count: {
          id: true,
        },
      }),
      this.prisma.aIMetrics.findMany({
        where,
        select: {
          totalTime: true,
          ttft: true,
          cost: true,
          model: true,
          createdAt: true,
          inputTokens: true,
          outputTokens: true,
          thinkingTokens: true,
        },
        orderBy: {
          createdAt: 'asc',
        },
      }),
    ]);

    // Calculate percentiles (P50, P95, P99)
    const sortedTimes = metrics
      .map(m => m.totalTime)
      .filter(t => t !== null)
      .sort((a, b) => a! - b!);

    const percentile = (arr: number[], p: number) => {
      if (arr.length === 0) return null;
      const index = Math.ceil((arr.length * p) / 100) - 1;
      return arr[index];
    };

    const p50 = percentile(sortedTimes as number[], 50);
    const p95 = percentile(sortedTimes as number[], 95);
    const p99 = percentile(sortedTimes as number[], 99);

    // Model distribution
    const modelCounts: Record<string, { count: number; avgTime: number; totalTime: number }> = {};
    metrics.forEach(m => {
      if (!modelCounts[m.model]) {
        modelCounts[m.model] = { count: 0, avgTime: 0, totalTime: 0 };
      }
      modelCounts[m.model].count++;
      modelCounts[m.model].totalTime += m.totalTime || 0;
    });

    Object.keys(modelCounts).forEach(model => {
      modelCounts[model].avgTime = Math.round(modelCounts[model].totalTime / modelCounts[model].count);
    });

    // Token usage
    const totalInputTokens = metrics.reduce((sum, m) => sum + (m.inputTokens || 0), 0);
    const totalOutputTokens = metrics.reduce((sum, m) => sum + (m.outputTokens || 0), 0);
    const totalThinkingTokens = metrics.reduce((sum, m) => sum + (m.thinkingTokens || 0), 0);

    return {
      overview: {
        avgResponseTime: Math.round(overview._avg.totalTime || 0),
        p50ResponseTime: p50,
        p95ResponseTime: p95,
        p99ResponseTime: p99,
        avgTTFT: Math.round(overview._avg.ttft || 0),
        totalMessages: overview._count.id,
        totalCost: Number((metrics.reduce((sum, m) => sum + (m.cost || 0), 0)).toFixed(6)),
        avgCostPerMessage: Number((overview._avg.cost || 0).toFixed(6)),
      },
      modelDistribution: Object.entries(modelCounts).map(([model, stats]) => ({
        model,
        count: stats.count,
        avgTime: stats.avgTime,
      })),
      tokenUsage: {
        totalInputTokens,
        totalOutputTokens,
        totalThinkingTokens,
        avgInputTokensPerMessage: Math.round(totalInputTokens / (metrics.length || 1)),
        avgOutputTokensPerMessage: Math.round(totalOutputTokens / (metrics.length || 1)),
      },
    };
  }

  // ==================== CACHE ANALYTICS ====================

  async getCacheAnalytics(query: StatsQueryDto): Promise<CacheAnalyticsResponse> {
    const { dateFrom, dateTo } = query;

    const where: any = {};
    if (dateFrom || dateTo) {
      where.createdAt = {};
      if (dateFrom) where.createdAt.gte = new Date(dateFrom);
      if (dateTo) where.createdAt.lte = new Date(dateTo);
    }

    // Get all metrics with cache info
    const [cacheHits, cacheMisses, cachedMetrics, nonCachedMetrics, allMetrics] = await Promise.all([
      this.prisma.aIMetrics.count({ where: { ...where, cacheHit: true } }),
      this.prisma.aIMetrics.count({ where: { ...where, cacheHit: false } }),
      this.prisma.aIMetrics.findMany({
        where: { ...where, cacheHit: true },
        select: { totalTime: true, createdAt: true },
        orderBy: { createdAt: 'asc' },
      }),
      this.prisma.aIMetrics.findMany({
        where: { ...where, cacheHit: false },
        select: { totalTime: true, createdAt: true },
        orderBy: { createdAt: 'asc' },
      }),
      this.prisma.aIMetrics.findMany({
        where,
        select: { cacheHit: true, createdAt: true },
        orderBy: { createdAt: 'asc' },
      }),
    ]);

    const totalQueries = cacheHits + cacheMisses;
    const hitRatePercent = totalQueries > 0
      ? Number(((cacheHits / totalQueries) * 100).toFixed(2))
      : 0;

    // Percentile helper
    const percentile = (arr: number[], p: number) => {
      if (arr.length === 0) return null;
      const index = Math.ceil((arr.length * p) / 100) - 1;
      return arr[Math.max(0, index)];
    };

    // Response time stats for cached queries
    const cachedTimes = cachedMetrics
      .map(m => m.totalTime)
      .filter((t): t is number => t !== null)
      .sort((a, b) => a - b);

    const cachedAvg = cachedTimes.length > 0
      ? Math.round(cachedTimes.reduce((s, t) => s + t, 0) / cachedTimes.length)
      : 0;

    // Response time stats for non-cached queries
    const nonCachedTimes = nonCachedMetrics
      .map(m => m.totalTime)
      .filter((t): t is number => t !== null)
      .sort((a, b) => a - b);

    const nonCachedAvg = nonCachedTimes.length > 0
      ? Math.round(nonCachedTimes.reduce((s, t) => s + t, 0) / nonCachedTimes.length)
      : 0;

    // Time saved estimation
    const avgTimeSavedMs = Math.max(0, nonCachedAvg - cachedAvg);
    const totalTimeSavedMs = avgTimeSavedMs * cacheHits;

    // Time series: group by date
    const timeSeriesMap: Record<string, { hits: number; misses: number }> = {};
    allMetrics.forEach(m => {
      const date = m.createdAt.toISOString().split('T')[0];
      if (!timeSeriesMap[date]) {
        timeSeriesMap[date] = { hits: 0, misses: 0 };
      }
      if (m.cacheHit) {
        timeSeriesMap[date].hits++;
      } else {
        timeSeriesMap[date].misses++;
      }
    });

    return {
      overview: {
        totalQueries,
        cacheHits,
        cacheMisses,
        hitRatePercent,
        avgTimeSavedMs,
        totalTimeSavedMs,
      },
      responseTimeComparison: {
        cached: {
          avg: cachedAvg,
          p50: percentile(cachedTimes, 50),
          p95: percentile(cachedTimes, 95),
        },
        nonCached: {
          avg: nonCachedAvg,
          p50: percentile(nonCachedTimes, 50),
          p95: percentile(nonCachedTimes, 95),
        },
      },
      timeSeries: Object.entries(timeSeriesMap)
        .map(([date, stats]) => ({
          date,
          hits: stats.hits,
          misses: stats.misses,
          hitRate: (stats.hits + stats.misses) > 0
            ? Number((stats.hits / (stats.hits + stats.misses)).toFixed(2))
            : 0,
        }))
        .sort((a, b) => a.date.localeCompare(b.date)),
    };
  }

  async getAIQuality(query: StatsQueryDto) {
    const { dateFrom, dateTo } = query;

    const where: any = {};

    if (dateFrom || dateTo) {
      where.createdAt = {};
      if (dateFrom) where.createdAt.gte = new Date(dateFrom);
      if (dateTo) where.createdAt.lte = new Date(dateTo);
    }

    // Get feedbacks
    const [totalFeedbacks, likeFeedbacks, dislikeFeedbacks, feedbacks] = await Promise.all([
      this.prisma.feedback.count({ where }),
      this.prisma.feedback.count({ where: { ...where, isLike: true } }),
      this.prisma.feedback.count({ where: { ...where, isLike: false } }),
      this.prisma.feedback.findMany({
        where: { ...where, isLike: false },
        select: {
          reason: true,
        },
      }),
    ]);

    // Count total messages in period
    const totalMessages = await this.prisma.message.count({
      where: {
        sender: 'bot',
        createdAt: where.createdAt,
      },
    });

    const feedbackRate = totalMessages > 0 ? totalFeedbacks / totalMessages : 0;
    const likeRatio = totalFeedbacks > 0 ? likeFeedbacks / totalFeedbacks : 0;
    const qualityScore = Math.round(likeRatio * 100);

    // Count dislike reasons
    const dislikeReasons: Record<string, number> = {};
    feedbacks.forEach(f => {
      const reason = f.reason || 'Khác';
      dislikeReasons[reason] = (dislikeReasons[reason] || 0) + 1;
    });

    return {
      overview: {
        totalFeedbacks,
        feedbackRate: Number(feedbackRate.toFixed(2)),
        likeCount: likeFeedbacks,
        dislikeCount: dislikeFeedbacks,
        likeRatio: Number(likeRatio.toFixed(2)),
        qualityScore,
      },
      dislikeReasons: Object.entries(dislikeReasons)
        .map(([reason, count]) => ({ reason, count }))
        .sort((a, b) => b.count - a.count),
    };
  }

  // ==================== SYSTEM STATS ====================

  async getSystemStats() {
    const now = new Date();
    const oneDayAgo = new Date(now.getTime() - 24 * 60 * 60 * 1000);
    const sevenDaysAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
    const thirtyDaysAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);

    const [
      totalUsers,
      totalConversations,
      totalMessages,
      activeUsers24h,
      activeUsers7d,
      activeUsers30d,
    ] = await Promise.all([
      this.prisma.user.count({ where: { deletedAt: null } }),
      this.prisma.conversation.count({ where: { isDeleted: false } }),
      this.prisma.message.count(),
      this.prisma.user.count({
        where: {
          conversations: {
            some: {
              messages: {
                some: {
                  createdAt: {
                    gte: oneDayAgo,
                  },
                },
              },
            },
          },
        },
      }),
      this.prisma.user.count({
        where: {
          conversations: {
            some: {
              messages: {
                some: {
                  createdAt: {
                    gte: sevenDaysAgo,
                  },
                },
              },
            },
          },
        },
      }),
      this.prisma.user.count({
        where: {
          conversations: {
            some: {
              messages: {
                some: {
                  createdAt: {
                    gte: thirtyDaysAgo,
                  },
                },
              },
            },
          },
        },
      }),
    ]);

    return {
      users: {
        total: totalUsers,
        active24h: activeUsers24h,
        active7d: activeUsers7d,
        active30d: activeUsers30d,
      },
      conversations: {
        total: totalConversations,
      },
      messages: {
        total: totalMessages,
      },
    };
  }

  // ==================== PHASE 3: HEALTH CHECK ====================

  async getHealthCheck(): Promise<HealthCheckResponse> {
    const timestamp = new Date().toISOString();

    // Check all services in parallel
    const [databaseHealth, aiServiceHealth, redisHealth] = await Promise.all([
      this.checkDatabaseHealth(),
      this.checkAIServiceHealth(),
      this.checkRedisHealth(),
    ]);

    // Determine overall status
    const services = { database: databaseHealth, aiService: aiServiceHealth, redis: redisHealth };
    const allUp = Object.values(services).every(s => s.status === 'up');
    const anyDown = Object.values(services).some(s => s.status === 'down');

    let status: 'healthy' | 'unhealthy' | 'degraded';
    if (allUp) {
      status = 'healthy';
    } else if (anyDown) {
      status = 'unhealthy';
    } else {
      status = 'degraded';
    }

    return {
      status,
      timestamp,
      services,
    };
  }

  private async checkDatabaseHealth(): Promise<ServiceHealth> {
    const start = Date.now();
    try {
      await this.prisma.$queryRaw`SELECT 1`;
      return {
        status: 'up',
        responseTime: Date.now() - start,
      };
    } catch (error) {
      return {
        status: 'down',
        responseTime: Date.now() - start,
        error: error instanceof Error ? error.message : 'Unknown database error',
      };
    }
  }

  private async checkAIServiceHealth(): Promise<ServiceHealth> {
    const start = Date.now();
    const aiServiceUrl = this.configService.get<string>('FASTAPI_URL') || 'http://localhost';
    const aiServicePort = this.configService.get<string>('FASTAPI_PORT') || '8001';
    const healthUrl = `${aiServiceUrl}:${aiServicePort}/health`;

    try {
      const response = await firstValueFrom(
        this.httpService.get(healthUrl).pipe(
          timeout(5000),
          catchError(() => of({ status: 500, data: null }))
        )
      );

      if (response.status === 200) {
        return {
          status: 'up',
          responseTime: Date.now() - start,
        };
      }
      return {
        status: 'down',
        responseTime: Date.now() - start,
        error: 'AI service not responding',
      };
    } catch (error) {
      return {
        status: 'down',
        responseTime: Date.now() - start,
        error: error instanceof Error ? error.message : 'Cannot connect to AI service',
      };
    }
  }

  private async checkRedisHealth(): Promise<ServiceHealth> {
    const start = Date.now();
    try {
      const result = await this.redisClient.ping();
      if (result === 'PONG') {
        return {
          status: 'up',
          responseTime: Date.now() - start,
        };
      }
      return {
        status: 'degraded',
        responseTime: Date.now() - start,
        error: 'Unexpected Redis response',
      };
    } catch (error) {
      return {
        status: 'down',
        responseTime: Date.now() - start,
        error: error instanceof Error ? error.message : 'Cannot connect to Redis',
      };
    }
  }

  // ==================== PHASE 3: ENHANCED SYSTEM STATS ====================

  async getEnhancedSystemStats(): Promise<SystemStatsResponse> {
    const now = new Date();
    const oneDayAgo = new Date(now.getTime() - 24 * 60 * 60 * 1000);
    const sevenDaysAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
    const thirtyDaysAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);

    const [
      // Active users
      activeUsers24h,
      activeUsers7d,
      activeUsers30d,
      // Messages count
      messagesLast24h,
      messagesLast7d,
      messagesLast30d,
      // Bot messages with metrics
      botMessagesLast24h,
      botMessagesLast7d,
      // Errors last 24h
      errorsLast24h,
      errorsLast7d,
      // Slow requests
      slowRequestsLast24h,
      // Performance metrics
      performanceMetrics,
    ] = await Promise.all([
      // Active users
      this.countActiveUsers(oneDayAgo),
      this.countActiveUsers(sevenDaysAgo),
      this.countActiveUsers(thirtyDaysAgo),
      // Messages
      this.prisma.message.count({ where: { createdAt: { gte: oneDayAgo } } }),
      this.prisma.message.count({ where: { createdAt: { gte: sevenDaysAgo } } }),
      this.prisma.message.count({ where: { createdAt: { gte: thirtyDaysAgo } } }),
      // Bot messages (for error calculation)
      this.prisma.message.count({ where: { createdAt: { gte: oneDayAgo }, sender: 'bot' } }),
      this.prisma.message.count({ where: { createdAt: { gte: sevenDaysAgo }, sender: 'bot' } }),
      // Errors
      this.prisma.aIMetrics.count({
        where: {
          createdAt: { gte: oneDayAgo },
          error: { not: null },
        },
      }),
      this.prisma.aIMetrics.count({
        where: {
          createdAt: { gte: sevenDaysAgo },
          error: { not: null },
        },
      }),
      // Slow requests (> 5000ms)
      this.prisma.aIMetrics.count({
        where: {
          createdAt: { gte: oneDayAgo },
          totalTime: { gt: 5000 },
        },
      }),
      // Performance
      this.prisma.aIMetrics.aggregate({
        where: {
          createdAt: { gte: oneDayAgo },
        },
        _avg: {
          totalTime: true,
        },
        _count: {
          id: true,
        },
      }),
    ]);

    const avgMessagesPerDay = messagesLast30d / 30;
    const errorPercentage24h = botMessagesLast24h > 0 ? (errorsLast24h / botMessagesLast24h) * 100 : 0;
    const errorPercentage7d = botMessagesLast7d > 0 ? (errorsLast7d / botMessagesLast7d) * 100 : 0;
    const slowPercentage = performanceMetrics._count.id > 0
      ? (slowRequestsLast24h / performanceMetrics._count.id) * 100
      : 0;

    return {
      activeUsers: {
        last24h: activeUsers24h,
        last7d: activeUsers7d,
        last30d: activeUsers30d,
      },
      requestRate: {
        messagesLast24h,
        messagesLast7d,
        avgMessagesPerDay: Math.round(avgMessagesPerDay),
      },
      errorRate: {
        last24h: {
          total: errorsLast24h,
          percentage: Number(errorPercentage24h.toFixed(2)),
        },
        last7d: {
          total: errorsLast7d,
          percentage: Number(errorPercentage7d.toFixed(2)),
        },
      },
      performance: {
        avgResponseTime: Math.round(performanceMetrics._avg.totalTime || 0),
        slowRequests24h: slowRequestsLast24h,
        slowRequestsPercentage: Number(slowPercentage.toFixed(2)),
      },
    };
  }

  private async countActiveUsers(since: Date): Promise<number> {
    return this.prisma.user.count({
      where: {
        conversations: {
          some: {
            messages: {
              some: {
                createdAt: { gte: since },
              },
            },
          },
        },
      },
    });
  }

  // ==================== PHASE 3: ENHANCED FEEDBACKS ====================

  async getFeedbacks(query: GetFeedbacksDto) {
    const {
      page = 1,
      limit = 20,
      isLike,
      userId,
      conversationId,
      search,
      dateFrom,
      dateTo,
      sortBy = 'createdAt',
      order = 'desc',
    } = query;

    const where: any = {};

    if (isLike !== undefined) {
      where.isLike = isLike;
    }

    if (userId) {
      where.userId = userId;
    }

    if (conversationId) {
      where.message = {
        conversationId,
      };
    }

    if (search) {
      where.reason = {
        contains: search,
        mode: 'insensitive',
      };
    }

    if (dateFrom || dateTo) {
      where.createdAt = {};
      if (dateFrom) where.createdAt.gte = new Date(dateFrom);
      if (dateTo) where.createdAt.lte = new Date(dateTo);
    }

    const orderBy: any = {};
    orderBy[sortBy] = order;

    const [data, total, likeStats] = await Promise.all([
      this.prisma.feedback.findMany({
        where,
        skip: (page - 1) * limit,
        take: limit,
        include: {
          user: {
            select: {
              id: true,
              fullName: true,
              email: true,
            },
          },
          message: {
            select: {
              id: true,
              content: true,
              conversationId: true,
              aiMetrics: {
                select: {
                  totalTime: true,
                  model: true,
                },
              },
              conversation: {
                select: {
                  id: true,
                  title: true,
                },
              },
            },
          },
        },
        orderBy,
      }),
      this.prisma.feedback.count({ where }),
      this.prisma.feedback.groupBy({
        by: ['isLike'],
        where,
        _count: {
          id: true,
        },
      }),
    ]);

    // Get the previous message (user question) for each feedback
    const feedbacksWithQuestion = await Promise.all(
      data.map(async (feedback) => {
        const userQuestion = await this.prisma.message.findFirst({
          where: {
            conversationId: feedback.message.conversationId,
            sender: 'user',
            createdAt: {
              lt: await this.prisma.message.findUnique({
                where: { id: feedback.messageId },
                select: { createdAt: true },
              }).then(m => m?.createdAt),
            },
          },
          orderBy: {
            createdAt: 'desc',
          },
          select: {
            content: true,
          },
        });

        return {
          id: feedback.id,
          messageId: feedback.messageId,
          userId: feedback.userId,
          user: feedback.user,
          message: {
            content: feedback.message.content,
            question: userQuestion?.content || null,
            conversationId: feedback.message.conversationId,
            conversation: feedback.message.conversation,
            aiMetrics: feedback.message.aiMetrics ? {
              responseTime: feedback.message.aiMetrics.totalTime,
              model: feedback.message.aiMetrics.model,
            } : null,
          },
          isLike: feedback.isLike,
          reason: feedback.reason,
          createdAt: feedback.createdAt,
          updatedAt: feedback.updatedAt,
        };
      })
    );

    const likesCount = likeStats.find(s => s.isLike === true)?._count.id || 0;
    const dislikesCount = likeStats.find(s => s.isLike === false)?._count.id || 0;
    const totalFiltered = likesCount + dislikesCount;

    return {
      data: feedbacksWithQuestion,
      total,
      page,
      limit,
      stats: {
        totalLikes: likesCount,
        totalDislikes: dislikesCount,
        likeRatio: totalFiltered > 0 ? Number((likesCount / totalFiltered).toFixed(2)) : 0,
      },
    };
  }

  // ==================== PHASE 3: FEEDBACK ANALYTICS ====================

  async getFeedbackAnalytics(query: StatsQueryDto): Promise<FeedbackAnalyticsResponse> {
    const { dateFrom, dateTo } = query;

    const where: any = {};
    if (dateFrom || dateTo) {
      where.createdAt = {};
      if (dateFrom) where.createdAt.gte = new Date(dateFrom);
      if (dateTo) where.createdAt.lte = new Date(dateTo);
    }

    // Get all feedbacks and related data
    const [
      totalFeedbacks,
      likeFeedbacks,
      dislikeFeedbacks,
      feedbacksWithReasons,
      totalBotMessages,
      feedbacksWithMetrics,
    ] = await Promise.all([
      this.prisma.feedback.count({ where }),
      this.prisma.feedback.count({ where: { ...where, isLike: true } }),
      this.prisma.feedback.count({ where: { ...where, isLike: false } }),
      this.prisma.feedback.findMany({
        where: { ...where, isLike: false },
        select: { reason: true },
      }),
      this.prisma.message.count({
        where: {
          sender: 'bot',
          createdAt: where.createdAt,
        },
      }),
      this.prisma.feedback.findMany({
        where,
        select: {
          isLike: true,
          createdAt: true,
          message: {
            select: {
              aiMetrics: {
                select: {
                  totalTime: true,
                },
              },
            },
          },
        },
      }),
    ]);

    const feedbackRate = totalBotMessages > 0 ? totalFeedbacks / totalBotMessages : 0;
    const likeRatio = totalFeedbacks > 0 ? likeFeedbacks / totalFeedbacks : 0;
    const qualityScore = Math.round(likeRatio * 100);

    // Count dislike reasons
    const dislikeReasons: Record<string, number> = {};
    feedbacksWithReasons.forEach(f => {
      const reason = f.reason || 'Không có lý do';
      dislikeReasons[reason] = (dislikeReasons[reason] || 0) + 1;
    });

    // Group feedbacks by date for time series
    const timeSeriesMap: Record<string, { likes: number; dislikes: number }> = {};
    feedbacksWithMetrics.forEach(f => {
      const date = f.createdAt.toISOString().split('T')[0];
      if (!timeSeriesMap[date]) {
        timeSeriesMap[date] = { likes: 0, dislikes: 0 };
      }
      if (f.isLike) {
        timeSeriesMap[date].likes++;
      } else {
        timeSeriesMap[date].dislikes++;
      }
    });

    // Feedback by response time ranges
    const responseTimeRanges = [
      { range: '0-1000ms', min: 0, max: 1000 },
      { range: '1000-2000ms', min: 1000, max: 2000 },
      { range: '2000-5000ms', min: 2000, max: 5000 },
      { range: '5000ms+', min: 5000, max: Infinity },
    ];

    const feedbackByResponseTime = responseTimeRanges.map(range => {
      const inRange = feedbacksWithMetrics.filter(f => {
        const time = f.message.aiMetrics?.totalTime;
        return time !== null && time !== undefined && time >= range.min && time < range.max;
      });
      const likes = inRange.filter(f => f.isLike).length;
      const dislikes = inRange.filter(f => !f.isLike).length;
      const total = likes + dislikes;

      return {
        responseTimeRange: range.range,
        totalMessages: total,
        likeCount: likes,
        dislikeCount: dislikes,
        likeRatio: total > 0 ? Number((likes / total).toFixed(2)) : 0,
      };
    });

    return {
      overview: {
        totalFeedbacks,
        feedbackRate: Number(feedbackRate.toFixed(2)),
        likeCount: likeFeedbacks,
        dislikeCount: dislikeFeedbacks,
        likeRatio: Number(likeRatio.toFixed(2)),
        qualityScore,
      },
      timeSeries: Object.entries(timeSeriesMap)
        .map(([date, stats]) => ({
          date,
          likeCount: stats.likes,
          dislikeCount: stats.dislikes,
          likeRatio: (stats.likes + stats.dislikes) > 0
            ? Number((stats.likes / (stats.likes + stats.dislikes)).toFixed(2))
            : 0,
        }))
        .sort((a, b) => a.date.localeCompare(b.date)),
      dislikeReasons: Object.entries(dislikeReasons)
        .map(([reason, count]) => ({ reason, count }))
        .sort((a, b) => b.count - a.count),
      feedbackByResponseTime,
    };
  }

  // ==================== PHASE 3: AI ERRORS TRACKING ====================

  async getAIErrors(query: GetFeedbacksDto): Promise<AIErrorsResponse> {
    const {
      page = 1,
      limit = 20,
      dateFrom,
      dateTo,
    } = query;

    const where: any = {
      error: { not: null },
    };

    if (dateFrom || dateTo) {
      where.createdAt = {};
      if (dateFrom) where.createdAt.gte = new Date(dateFrom);
      if (dateTo) where.createdAt.lte = new Date(dateTo);
    }

    const [data, total, errorsByType] = await Promise.all([
      this.prisma.aIMetrics.findMany({
        where,
        skip: (page - 1) * limit,
        take: limit,
        include: {
          message: {
            select: {
              id: true,
              conversationId: true,
              content: true,
              conversation: {
                select: {
                  userId: true,
                  user: {
                    select: {
                      email: true,
                    },
                  },
                },
              },
            },
          },
        },
        orderBy: {
          createdAt: 'desc',
        },
      }),
      this.prisma.aIMetrics.count({ where }),
      this.prisma.aIMetrics.groupBy({
        by: ['errorType'],
        where,
        _count: {
          id: true,
        },
      }),
    ]);

    // Get user questions for each error
    const errorsWithQuestions = await Promise.all(
      data.map(async (metric) => {
        const userQuestion = await this.prisma.message.findFirst({
          where: {
            conversationId: metric.message.conversationId,
            sender: 'user',
            createdAt: {
              lt: await this.prisma.message.findUnique({
                where: { id: metric.messageId },
                select: { createdAt: true },
              }).then(m => m?.createdAt),
            },
          },
          orderBy: {
            createdAt: 'desc',
          },
          select: {
            content: true,
          },
        });

        return {
          messageId: metric.messageId,
          conversationId: metric.message.conversationId,
          userId: metric.message.conversation.userId,
          userEmail: metric.message.conversation.user.email,
          errorType: metric.errorType || 'UNKNOWN',
          errorMessage: metric.error || 'Unknown error',
          question: userQuestion?.content || 'N/A',
          timestamp: metric.createdAt.toISOString(),
          metadata: {
            model: metric.model,
            retryCount: metric.retryCount || 0,
          },
        };
      })
    );

    return {
      data: errorsWithQuestions,
      total,
      errorsByType: errorsByType
        .filter(e => e.errorType !== null)
        .map(e => ({
          type: e.errorType!,
          count: e._count.id,
        }))
        .sort((a, b) => b.count - a.count),
    };
  }
}
