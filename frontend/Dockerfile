FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html
COPY funlab-logo.jpeg /usr/share/nginx/html/funlab-logo.jpeg
COPY logo.jpg /usr/share/nginx/html/logo.jpg

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
