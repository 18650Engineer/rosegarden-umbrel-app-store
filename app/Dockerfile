FROM python:3.13-alpine
WORKDIR /app
COPY --chown=1000:1000 server.py ./server.py
COPY --chown=1000:1000 qrcode/ ./qrcode/
COPY --chown=1000:1000 static/ ./static/
USER 1000:1000
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ROSE_HOST=0.0.0.0 ROSE_PORT=8765 ROSE_BRIDGE_BACKEND=rest
EXPOSE 8765
CMD ["python3", "server.py"]
