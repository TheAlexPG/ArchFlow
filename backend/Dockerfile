FROM python:3.12-slim AS builder

WORKDIR /app
COPY pyproject.toml .

RUN pip install uv && \
    uv pip install --system -r pyproject.toml

COPY . .

FROM python:3.12-slim

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
# Copy the whole bin/ from the builder instead of cherry-picking gunicorn+uvicorn —
# we also need alembic (and anything else Python deps install). The builder is a
# clean python:3.12-slim + uv, so nothing unwanted lands here.
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app .

EXPOSE 8001

# Matches docker-compose.prod.yml command so `docker run` alone yields the
# same behaviour as the deployed stack.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
