FROM node:22-alpine AS dev

WORKDIR /app

COPY package.json package-lock.json docker-entrypoint.sh ./
RUN npm ci \
    && sha256sum package-lock.json | awk '{print $1}' > node_modules/.package-lock.sha256 \
    && chmod 755 docker-entrypoint.sh \
    && mv docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

COPY . .

EXPOSE 5173

# 0.0.0.0 is the container interface. Compose publishes it on loopback only.
CMD ["docker-entrypoint.sh"]

FROM dev AS build

RUN npm run build

FROM nginx:1.27-alpine AS prod

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
