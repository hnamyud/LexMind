export interface ServiceHealth {
  status: 'up' | 'down' | 'degraded';
  responseTime?: number; // ms
  error?: string;
}

export interface HealthCheckResponse {
  status: 'healthy' | 'unhealthy' | 'degraded';
  timestamp: string;
  services: {
    database: ServiceHealth;
    aiService: ServiceHealth;
    redis: ServiceHealth;
  };
}

export interface SystemStatsResponse {
  activeUsers: {
    last24h: number;
    last7d: number;
    last30d: number;
  };
  requestRate: {
    messagesLast24h: number;
    messagesLast7d: number;
    avgMessagesPerDay: number;
  };
  errorRate: {
    last24h: {
      total: number;
      percentage: number;
    };
    last7d: {
      total: number;
      percentage: number;
    };
  };
  performance: {
    avgResponseTime: number;
    slowRequests24h: number; // requests > 5s
    slowRequestsPercentage: number;
  };
}

export interface FeedbackAnalyticsResponse {
  overview: {
    totalFeedbacks: number;
    feedbackRate: number;
    likeCount: number;
    dislikeCount: number;
    likeRatio: number;
    qualityScore: number;
  };
  timeSeries: Array<{
    date: string;
    likeCount: number;
    dislikeCount: number;
    likeRatio: number;
  }>;
  dislikeReasons: Array<{
    reason: string;
    count: number;
  }>;
  feedbackByResponseTime: Array<{
    responseTimeRange: string;
    totalMessages: number;
    likeCount: number;
    dislikeCount: number;
    likeRatio: number;
  }>;
}

export interface AIErrorsResponse {
  data: Array<{
    messageId: string;
    conversationId: string;
    userId: string;
    userEmail?: string;
    errorType: string;
    errorMessage: string;
    question: string;
    timestamp: string;
    metadata: {
      model: string;
      retryCount: number;
    };
  }>;
  total: number;
  errorsByType: Array<{
    type: string;
    count: number;
  }>;
}
