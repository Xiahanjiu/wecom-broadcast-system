# Dockerfile for WebSocket Relay
# 部署到 Fly.io / Render / 任意支持 Docker 的平台
FROM python:3.11-slim

WORKDIR /app

COPY relay_requirements.txt .
RUN pip install --no-cache-dir -r relay_requirements.txt

COPY relay.py .

# 暴露端口 (Fly.io / Render 通过 PORT 环境变量注入)
ENV PORT=8080

EXPOSE 8080

CMD ["python", "relay.py"]
