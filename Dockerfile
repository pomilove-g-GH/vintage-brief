FROM python:3.12-slim

# 필수 시스템 패키지 (yt-dlp 가 ffmpeg 없이도 메타데이터 추출 가능하므로 최소 구성)
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# 영구 볼륨 마운트 위치
ENV DATA_ROOT=/data
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["gunicorn", "server:app", \
     "--workers", "2", \
     "--threads", "2", \
     "--timeout", "180", \
     "--bind", "0.0.0.0:8080"]
