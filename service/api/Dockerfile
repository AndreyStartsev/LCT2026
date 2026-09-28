# Сборка из каталога service/: нужна схема базы из service/db.
FROM node:22-alpine AS build
WORKDIR /app
COPY api/package.json api/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY api/tsconfig.json ./
COPY api/src ./src
RUN npm run build && npm prune --omit=dev

FROM node:22-alpine
# шрифт с кириллицей для протокола в PDF
RUN apk add --no-cache font-dejavu
WORKDIR /app
ENV NODE_ENV=production PORT=8080 SCHEMA_PATH=/app/db/schema.sql
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY api/package.json ./
COPY db/schema.sql ./db/schema.sql
USER node
EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=3s --retries=30 \
  CMD wget -qO- http://127.0.0.1:8080/api/v1/health >/dev/null || exit 1
CMD ["node", "dist/server.js"]
