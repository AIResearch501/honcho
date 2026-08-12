# Honcho MCP Server — runs the Cloudflare Worker locally via wrangler dev.
# Node 22 (Debian bookworm, glibc 2.36) is required: the arm64 workerd
# binary needs glibc >= 2.32, which Alpine/bullseye images lack.
FROM node:22-bookworm-slim

WORKDIR /app

# Install bun for lockfile-compatible dependency management.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl unzip ca-certificates \
    && curl -fsSL https://bun.sh/install | bash \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get purge -y --auto-remove curl unzip \
    # Make bun available to the non-root 'app' user: move just the binary
    # and symlink it (the installer's bunx symlink points into /root).
    && mkdir -p /usr/local/bun/bin \
    && mv /root/.bun/bin/bun /usr/local/bun/bin/bun \
    && ln -sf /usr/local/bun/bin/bun /usr/local/bin/bun \
    && ln -sf /usr/local/bun/bin/bun /usr/local/bin/bunx

ENV PATH="/usr/local/bun/bin:$PATH"

# Install dependencies first for better layer caching.
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

# Copy the Worker source and wrangler config.
COPY src/ ./src/
COPY wrangler.toml ./

# wrangler dev runs as root in the container by default; create a non-root user.
RUN addgroup --system app && adduser --system --group app \
    && mkdir -p /home/app && chown app:app /home/app \
    && chown -R app:app /app
USER app
ENV HOME=/home/app

# Local dev server port (mcp-remote / MCP clients connect here).
EXPOSE 8787

# HONCHO_API_URL is set via compose; wrangler dev serves the Worker at 0.0.0.0:8787.
CMD ["bunx", "wrangler", "dev", "--ip", "0.0.0.0", "--port", "8787"]
