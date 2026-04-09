"""
Simple test script for custom proxy API (OpenAI-compatible)
"""

import sys
import os
import time
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path
from openai import OpenAI

# Load environment variables
ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=ROOT_DIR / ".env")

# Configuration
BASE_URL = "http://localhost:20128/v1"
API_KEY = os.getenv("LOCAL_API_KEY", "")


def main():
    # Get API key from command line or environment
    api_key = None
    if len(sys.argv) > 1:
        api_key = sys.argv[1]
    else:
        api_key = API_KEY
    
    if not api_key:
        print("❌ API Key not found!")
        print("\n📝 Usage:")
        print("   Option 1 - Set in .env file:")
        print("      LOCAL_API_KEY=your-api-key")
        print("      python test_proxy_model.py")
        print("\n   Option 2 - Pass as argument:")
        print("      python test_proxy_model.py your-api-key")
        sys.exit(1)
    
    print("=" * 70)
    print("PROXY MODEL TEST")
    print("=" * 70)
    print(f"Base URL: {BASE_URL}")
    masked_key = f"{'*' * (len(api_key) - 4)}{api_key[-4:]}" if len(api_key) > 4 else "****"
    print(f"API Key: {masked_key}\n")
    
    # Initialize OpenAI client
    client = OpenAI(
        api_key=api_key,
        base_url=BASE_URL
    )
    
    try:
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        start_perf = time.perf_counter()
        print(f"Sending request at: {started_at}\n")

        response = client.chat.completions.create(
            model="gh/claude-opus-4.5",
            messages=[
                {
                    "role": "system",
                    "content": "Bạn là một chuyên gia pháp lý chuyên về luật giao thông Việt Nam. Trả lời ngắn gọn và chính xác."
                },
                {
                    "role": "user",
                    "content": "Hình phạt đối với lái xe vượt đèn đỏ là bao nhiêu?"
                }
            ],
            temperature=0.7,
            max_tokens=1500
        )

        ended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        elapsed = time.perf_counter() - start_perf
        
        print("✅ Success!")
        print("-" * 70)
        print(f"Response:\n{response.choices[0].message.content}")
        print("-" * 70)
        print(f"Request started: {started_at}")
        print(f"Request ended:   {ended_at}")
        print(f"Latency: {elapsed:.3f}s ({elapsed * 1000:.0f} ms)")
        print(f"\nModel: {response.model}")
        print(f"Tokens used: {response.usage.total_tokens}")
        
    except Exception as e:
        failed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"❌ Error at {failed_at}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

