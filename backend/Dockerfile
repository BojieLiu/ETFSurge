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
    # R5-2-4: mootdx 与 pandas_ta 同模式 --no-deps（mootdx 0.11.7 依赖 httpx<0.26 与 requirements 的 httpx>=0.27 冲突；
    # 实测 httpx 0.28.x + mootdx 0.11.7 运行时兼容）。prettytable/tdxpy/tenacity 为其依赖，同 --no-deps 显式安装
    # （tenacity 不为 akshare 1.18.x 依赖，漏装会致容器内 mootdx ModuleNotFoundError → 降级链第一环空转，见 round6 诊断）；
    # py-mini-racer 由 akshare 依赖自动携带，httpx/click/tqdm/typing-extensions 由 requirements 提供。
    pip install --no-deps "mootdx>=0.11.7" "prettytable>=3.0" "tdxpy>=0.2.7" "tenacity>=8.0" && \
    pip install "numpy>=1.22,<2.5" && \
    pip install -r requirements.txt && \
    pip install "numba>=0.66.0"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
