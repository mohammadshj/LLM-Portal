# syntax=docker/dockerfile:1
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt .
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir -r requirements.txt
ARG INSTALL_LOCAL_TOKENIZERS=0
RUN --mount=type=secret,id=proxy_ca \
    if [ "$INSTALL_LOCAL_TOKENIZERS" = "1" ]; then \
      if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
      pip install --no-cache-dir tokenizers==0.22.2; \
    fi
RUN useradd --create-home portal && mkdir /app/staticfiles && chown portal:portal /app/staticfiles
COPY --chown=portal:portal backend/ .
RUN chmod -R a+rX /app
USER portal
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--timeout-graceful-shutdown", "25"]
