FROM python:3.11-slim AS builder
WORKDIR /build
RUN pip install --no-cache-dir --upgrade pip
COPY pyproject.toml ./
COPY app/ ./app/
ARG INSTALL_EXTRA=web
RUN pip install --no-cache-dir --prefix=/install ".[${INSTALL_EXTRA}]"

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /install /usr/local
COPY app/ ./app/
COPY .claude/skills/recipe-from-url/ ./.claude/skills/recipe-from-url/
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENV PYTHONUNBUFFERED=1 \
    APP_ROLE=web \
    RECIPES_DIR=/app/recipes \
    DATA_DIR=/app/data
EXPOSE 3141
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3141", "--proxy-headers", "--forwarded-allow-ips=*"]
