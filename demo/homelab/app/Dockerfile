FROM python:3.12-alpine
WORKDIR /app
COPY server.py /app/server.py
ENV PORT=8080 HEALTH_FILE=/data/health
EXPOSE 8080
HEALTHCHECK --interval=2s --timeout=1s --retries=3 --start-period=2s \
  CMD wget -qO- http://127.0.0.1:8080/health || exit 1
CMD ["python", "/app/server.py"]
