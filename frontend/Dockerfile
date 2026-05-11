FROM mirror.gcr.io/library/node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# Vite reads VITE_* vars at build time and inlines them into the bundle.
# Default baked in so the prod image deep-links to self-hosted PAF.
ARG VITE_PAF_URL=https://79.76.108.77:8080/agentFactory
ENV VITE_PAF_URL=${VITE_PAF_URL}
RUN npm run build

FROM mirror.gcr.io/nginxinc/nginx-unprivileged:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY --from=build /app/dist/index.html /usr/share/nginx/html/index.html
COPY nginx.conf /etc/nginx/conf.d/default.conf
# nginx-unprivileged listens on 8080 (non-root can't bind 80)
EXPOSE 8080
