-- CreateTable
CREATE TABLE "ai_metrics" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "message_id" UUID NOT NULL,
    "model" TEXT NOT NULL,
    "time_to_first_token" INTEGER,
    "total_time" INTEGER,
    "graph_query_time" INTEGER,
    "web_search_time" INTEGER,
    "input_tokens" INTEGER,
    "output_tokens" INTEGER,
    "thinking_tokens" INTEGER,
    "tool_calls" INTEGER DEFAULT 0,
    "tool_call_details" JSONB,
    "cost" DOUBLE PRECISION,
    "error" TEXT,
    "error_type" TEXT,
    "retry_count" INTEGER DEFAULT 0,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ai_metrics_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "ai_metrics_message_id_key" ON "ai_metrics"("message_id");

-- CreateIndex
CREATE INDEX "ai_metrics_message_id_idx" ON "ai_metrics"("message_id");

-- CreateIndex
CREATE INDEX "ai_metrics_created_at_idx" ON "ai_metrics"("created_at");

-- CreateIndex
CREATE INDEX "ai_metrics_model_idx" ON "ai_metrics"("model");

-- CreateIndex
CREATE INDEX "ai_metrics_total_time_idx" ON "ai_metrics"("total_time");

-- AddForeignKey
ALTER TABLE "ai_metrics" ADD CONSTRAINT "ai_metrics_message_id_fkey" FOREIGN KEY ("message_id") REFERENCES "messages"("id") ON DELETE CASCADE ON UPDATE CASCADE;
