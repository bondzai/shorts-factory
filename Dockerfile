# One container, one operator. ffmpeg for the mux, python for everything else.
# The database and renders live in /data — mount a volume there or lose them.
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY factory ./factory
COPY prompts ./prompts
COPY docs ./docs
COPY data/concepts ./data/concepts
COPY config.toml ./
RUN pip install --no-cache-dir . && mkdir -p /app/data /app/channels
# The package lands in site-packages; everything it reads at runtime is here.
ENV FACTORY_ROOT=/app
VOLUME ["/app/data", "/app/channels"]
EXPOSE 8765
CMD ["factory", "serve", "--host", "0.0.0.0", "--port", "8765"]
