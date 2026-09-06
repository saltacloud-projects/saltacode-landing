# syntax=docker/dockerfile:1.7

FROM node:24.17.0-alpine AS dependencies
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/landing/package.json apps/landing/package.json
RUN pnpm install --frozen-lockfile --filter @saltacode/frontend...

FROM dependencies AS build
COPY apps/landing/astro.config.ts apps/landing/tsconfig.json apps/landing/
COPY apps/landing/src apps/landing/src
COPY apps/landing/public apps/landing/public
RUN pnpm --filter @saltacode/frontend build

FROM node:24.17.0-alpine AS runtime
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=8080
WORKDIR /app
COPY --from=build --chown=node:node /app/apps/landing/dist ./dist
COPY --chown=node:node apps/landing/server.mjs ./server.mjs
USER node
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:' + (process.env.PORT || '8080') + '/healthz').then((response) => { if (!response.ok) process.exit(1); }).catch(() => process.exit(1));"]
CMD ["node", "server.mjs"]
