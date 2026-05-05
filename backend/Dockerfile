FROM node:20-bookworm-slim

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends openssl ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY . .
RUN npx prisma generate

EXPOSE 4000

# Dev: tsx watch reloads on source changes (compose mounts ./backend over /app).
CMD ["npx", "tsx", "watch", "src/server.ts"]
