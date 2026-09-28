FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
# шаблон и скрипт лимита: точка входа образа подставляет ${MAX_BODY_MB} перед запуском
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY 10-body-limit.envsh /docker-entrypoint.d/10-body-limit.envsh
COPY --from=build /app/dist /usr/share/nginx/html
