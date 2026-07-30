FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# pandas_ta hard-pins numba==0.61.2 which can't build from source on Python 3.14.
# Split into 4 steps: 1) pandas_ta --no-deps avoids pin; 2) pin numpy<2.5;
# 3) install requirements (numpy satisfied, stays <2.5); 4) install numba 0.66.0.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-deps "pandas_ta>=0.3.14b0" && \
    pip install "numpy>=1.22,<2.5" && \
    pip install -r requirements.txt && \
    pip install "numba>=0.66.0"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
