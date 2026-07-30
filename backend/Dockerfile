FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# pandas_ta removed from requirements.txt because numba (its dep) doesn't support Python 3.14.
# Install separately with --no-deps; pandas_ta works fine without numba (pure Python fallback).
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt && \
    pip install --no-deps "pandas_ta>=0.3.14b0"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
