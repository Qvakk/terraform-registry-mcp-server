# Multi-stage build for Terraform MCP Server
FROM python:3.13-alpine3.22 AS builder

RUN apk add --no-cache build-base libffi-dev

WORKDIR /app
COPY pyproject.toml .
COPY terraform_mcp_server ./terraform_mcp_server

RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir .

# Final stage
FROM python:3.13-alpine3.22

RUN apk add --no-cache ca-certificates libffi

COPY --from=builder /opt/venv /opt/venv

RUN adduser -D -u 1000 mcp && chown -R mcp:mcp /opt/venv

USER mcp

ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PORT=3002
ENV TRANSPORT_MODE=http

EXPOSE 3002

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import socket; s = socket.create_connection(('localhost', 3002), timeout=5); s.close()" || exit 1

CMD ["terraform-mcp-server"]
