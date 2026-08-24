FROM python:3.12-bookworm@sha256:80f5d259a5969c86f6c92145d572de4a68c68e0edd28d4367dec0fb411b42af3
WORKDIR /app
COPY pyproject.toml /app/pyproject.toml
COPY src /app/src
COPY inventory /app/inventory
RUN pip install --no-cache-dir '.[kafka]'
ENV INGEST_INVENTORY_PATH=/app/inventory/default.yaml
