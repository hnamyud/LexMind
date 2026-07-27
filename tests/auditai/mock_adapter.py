#!/usr/bin/env python3
"""Minimal mock HTTP target for guerrilla AuditAI runs.

Intentionally weak: one SEED blurb for all questions (not per-case RAG).
Empty response contexts so faithfulness uses dataset case.contexts.
Do not treat high scores with a smarter mock as product quality.
"""
from __future__ import annotations
import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer

SEED = 'Hệ thống chatbot AI hỗ trợ tra cứu và tư vấn Nghị định 168/2024/NĐ-CP và Luật Đường bộ 2024, sử dụng kiến trúc RAG (Retrieval-Augmented Generation) kết hợp Knowledge Graph Neo4j và Web Search để cung cấp câu trả lời chính xác, có trích dẫn nguồn pháp lý. Hệ thống tự động nhận biết ngữ cảnh để phản hồi theo phong cách tự nhiên hoặc chuẩn mực pháp lý. Động lực & Mục tiêu Tính năng nổi bật Kiến trúc hệ thống Tech Stack Cấu trúc thư mục Database Schema AI Service — RAG Pipeline Benchmark API Endpoints Hướng dẫn cài đặt & chạy Chạy bằng Docker Biến môi trường Đóng góp License Luật giao thông Việt Nam thay đổi thường xuyên và có nhiều điều khoản phức tạp khiến người dân khó tra cứu chính xác. Nghị định 168/2024/NĐ-CP với mức phạt mới đã gây ra nhiều thắc mắc trong cộng đồng.'
ATTACK = re.compile(
    r"(ignore all previous|system prompt|api key|bỏ qua mọi|tiết lộ)",
    re.I,
)

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        q = str(body.get("question") or "")
        if ATTACK.search(q):
            ans = "I cannot reveal system prompts or secrets."
        elif SEED:
            # Weak: same SEED for every question (honest FAIL under strict judge)
            ans = "Based on available docs: " + SEED[:500]
        else:
            ans = f"(mock) no seed docs for: {q[:80]}"
        raw = json.dumps({"answer": ans, "contexts": []}, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

print("mock adapter http://127.0.0.1:18080/chat (weak SEED, empty contexts)")
HTTPServer(("127.0.0.1", 18080), H).serve_forever()
