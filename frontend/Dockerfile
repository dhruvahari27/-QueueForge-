FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html theme.css theme.js live-bridge.js console-actions.js live-wiring.js /usr/share/nginx/html/
EXPOSE 80
