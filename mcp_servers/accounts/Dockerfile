FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
COPY pyproject.toml ./
COPY accounts_mcp ./accounts_mcp
RUN uv sync --no-cache --no-dev

EXPOSE 8080
CMD ["uv", "run", "uvicorn", "accounts_mcp.app:app", "--host", "0.0.0.0", "--port", "8080"]
