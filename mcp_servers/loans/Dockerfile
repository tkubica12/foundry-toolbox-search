FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
COPY pyproject.toml ./
COPY loans_mcp ./loans_mcp
RUN uv sync --no-cache --no-dev

EXPOSE 8080
CMD ["uv", "run", "uvicorn", "loans_mcp.app:app", "--host", "0.0.0.0", "--port", "8080"]
