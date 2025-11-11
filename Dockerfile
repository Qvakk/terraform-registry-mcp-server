# Multi-stage build for Terraform MCP Server
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml .
COPY terraform_mcp_server ./terraform_mcp_server

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .

# Final stage
FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy from builder
COPY --from=builder /app .
RUN pip install --no-cache-dir -e .

# Create non-root user
RUN useradd -m -u 1000 mcp && chown -R mcp:mcp /app

USER mcp

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=3002
ENV TRANSPORT_MODE=http

EXPOSE 3002

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:3002/health', timeout=5)" || exit 1

# Run the server
CMD ["terraform-mcp-server"]
