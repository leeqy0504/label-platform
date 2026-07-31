FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/node:22-alpine AS build

WORKDIR /app
COPY web/package.json web/package-lock.json ./

RUN npm config set registry https://registry.npmmirror.com \
    && npm ci

COPY web ./
COPY docs/user-guide.html /docs/user-guide.html
COPY docs/user-guide-assets /docs/user-guide-assets
RUN npm run build

FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/nginx:1.27-alpine
COPY deploy/nginx.dev.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
