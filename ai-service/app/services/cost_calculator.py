"""
services/cost_calculator.py
────────────────────────────
Tính toán chi phí ước tính dựa trên Gemini Flash pricing.

Hàm public:
  calculate_cost(input_tokens, output_tokens, thinking_tokens) → float (USD)
"""


def calculate_cost(input_tokens: int, output_tokens: int, thinking_tokens: int) -> float:
    """
    Calculate estimated cost based on Gemini Flash pricing.

    Gemini Flash Preview pricing (as of 2026):
    - Input: $0.075 per 1M tokens
    - Output: $0.30 per 1M tokens
    - Thinking: $0.30 per 1M tokens (same as output)

    Returns cost in USD.
    """
    input_cost = (input_tokens / 1_000_000) * 0.075
    output_cost = (output_tokens / 1_000_000) * 0.30
    thinking_cost = (thinking_tokens / 1_000_000) * 0.30

    total_cost = input_cost + output_cost + thinking_cost
    return round(total_cost, 6)  # Round to 6 decimal places
