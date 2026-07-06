FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com \
    && pip install --no-cache-dir uv -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com

COPY knowledge/ ./knowledge/
COPY mcp_data/ ./mcp_data/
COPY optclaw/ ./optclaw/
COPY skills/ ./skills/
COPY .env api_server.py config.yaml extensions_config.json ./

RUN mkdir -p /app/knowledge/faiss_index

EXPOSE 8000

CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "asyncio"]
