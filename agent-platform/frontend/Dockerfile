# =============================================================================
# Agent Platform Admin — Dockerfile
# Multi-stage: node build → nginx static
# =============================================================================

# ---- Stage 1: Build ---------------------------------------------------------
FROM node:26.8.1-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
RUN npm run build

# ---- Stage 2: Serve ---------------------------------------------------------
FROM nginx:1.31.4-alpine AS runtime

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Custom nginx config (SPA fallback + API proxy)
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built static files
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
