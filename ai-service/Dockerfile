# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/tmp/huggingface

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pip_list.json ./pip_list.json

# Build requirements from pinned pip_list.json while skipping known non-runtime/platform-specific packages.
RUN python - <<'PY'
import json
from pathlib import Path

skip = {
    "pip",
    "setuptools",
    "wheel",
    "pyreadline3",  # windows-only helper
    # Development and notebook-only tooling captured from local env.
    "pytest",
    "ipython",
    "ipython-pygments-lexers",
    "asttokens",
    "executing",
    "stack-data",
    "pure-eval",
    "prompt-toolkit",
    "iniconfig",
    "pluggy",
    "pygments",
    "traitlets",
    "matplotlib-inline",
    "jedi",
    "parso",
    "pyproject-hooks",
    "build",
    # Flask stack is not used by this FastAPI service at runtime.
    "flask",
    "flask-cors",
    "werkzeug",
    "itsdangerous",
    "blinker",
    # Unused package that pulls in the legacy google-generativeai stack.
    "generativeai",
    # Legacy package conflicts with langchain-google-genai in this stack.
    "google-generativeai",
    # This is a transitive dependency of langchain-google-genai.
    "google-ai-generativelanguage",
    # CUDA compiler package captured from local env, not needed for CPU runtime.
    "triton",
    # Not used by this service and causes resolver conflicts with langchain-core<1.0.
    "langgraph-prebuilt",
    # Not required for in-process graph execution.
    "langgraph-sdk",
}

packages = json.loads(Path("pip_list.json").read_text(encoding="utf-8"))
lines = []

# Compatibility overrides for the LangChain/LangGraph stack on Python 3.11.
overrides = {
    "langchain-core": "0.3.84",
    "langgraph": "0.6.7",
    "langgraph-checkpoint": "2.1.2",
    "langgraph-checkpoint-postgres": "3.0.4",
    # langchain-community 0.3.24 requires langsmith<0.4.
    "langsmith": "0.3.45",
}

# Runtime packages imported by the app that may be missing from pip_list snapshots.
required_packages = {
    "langchain-openai",
    "redis>=5.0.0",
    "redisvl>=0.3.0",
}

for pkg in packages:
    name = (pkg.get("name") or "").strip()
    version = (pkg.get("version") or "").strip()
    lname = name.lower()

    if not name or lname in skip:
        continue

    # Ignore GPU-specific packages if they appear in future snapshots.
    if lname.startswith("nvidia-"):
        continue

    # Force CPU-only torch to avoid pulling CUDA runtime libraries.
    if lname == "torch":
        lines.append("torch==2.6.0+cpu")
        continue

    if lname in overrides:
        lines.append(f"{name}=={overrides[lname]}")
        continue

    lines.append(f"{name}=={version}" if version else name)

Path("requirements.txt").write_text(
    "\n".join(sorted(set(lines) | required_packages, key=str.lower)) + "\n",
    encoding="utf-8",
)
PY

RUN --mount=type=cache,target=/root/.cache/pip \
    PIP_NO_CACHE_DIR=0 pip install --upgrade pip \
    && PIP_NO_CACHE_DIR=0 pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/tmp/huggingface \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system app && useradd --system --gid app --create-home app

COPY --from=builder /opt/venv /opt/venv
COPY app ./app
COPY main.py ./main.py

RUN chown -R app:app /app
USER app

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=3)" || exit 1

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
