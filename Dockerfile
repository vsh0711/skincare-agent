FROM python:3.12-slim
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

COPY pyproject.toml uv.lock* ./
RUN uv sync --locked --no-dev

COPY agents/stage4_foundry_hosted.py .
COPY data/ ./data/

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8088

CMD ["python", "stage4_foundry_hosted.py"]
