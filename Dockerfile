# syntax=docker/dockerfile:1.6
#
# EduPilot Backend — 멀티스테이지 Docker 이미지
#
# 목표:
#  - 최종 이미지 크기 < 500MB (LangGraph 포함)
#  - python:3.11-slim 베이스 (alpine 은 numpy/tiktoken 빌드 이슈로 회피)
#  - 빌드 툴은 builder 스테이지에만 존재 → runtime 스테이지는 순수 Python 런타임
#  - 비root 유저로 실행
#
# 빌드:
#   docker build -t <dockerhub_user>/edupilot-backend:vX.Y.Z .
#
# 실행 (로컬 검증):
#   docker run --rm -p 8000:8000 --env-file .env <dockerhub_user>/edupilot-backend:vX.Y.Z
#   curl http://localhost:8000/health

# ============================================================
# Stage 1: builder — 의존성 설치
# ============================================================
FROM python:3.11-slim AS builder

# pydantic-core (rust) 등 네이티브 휠 빌드에 필요한 최소 도구
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /install

# requirements 만 먼저 복사해 Docker layer cache 활용
COPY requirements.txt .

# --user 로 /root/.local 에 설치 → runtime 스테이지로 통째 복사
# --no-cache-dir 로 pip cache 층 생성 방지
RUN pip install --no-cache-dir --user --upgrade pip \
    && pip install --no-cache-dir --user -r requirements.txt


# ============================================================
# Stage 2: runtime — 최소 런타임
# ============================================================
FROM python:3.11-slim AS runtime

# 런타임에 필요한 최소 패키지 (curl 은 HEALTHCHECK 용)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# 비root 유저로 실행
RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --home /home/app --shell /bin/bash app

# Python 런타임 환경 변수
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH=/home/app/.local/bin:$PATH \
    PYTHONPATH=/app

WORKDIR /app

# builder 에서 설치한 pip 패키지를 /home/app/.local 로 복사
COPY --from=builder --chown=app:app /root/.local /home/app/.local

# 애플리케이션 소스 (.dockerignore 에 걸러진 파일만)
COPY --chown=app:app app ./app
COPY --chown=app:app sql ./sql

USER app

EXPOSE 8000

# 컨테이너 자체 헬스체크 — Nginx 뒤에서도 유효
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# uvicorn workers=2 → t3.small (2GB) 에 적합
# 메모리 더 여유있으면 --workers 4 로 올릴 것
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--access-log", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
