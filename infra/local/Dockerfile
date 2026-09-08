# Keep the runtime base fixed to the same Firefly release as this fork branch.
FROM fireflyiii/core:version-6.6.6

WORKDIR /var/www/html

# Overlay the fork's application source without replacing the image's locked
# Composer dependencies. Rebuild after PHP, routes, config, migration, view or
# compiled public-asset changes in this repository.
COPY app ./app
COPY bootstrap ./bootstrap
COPY config ./config
COPY database ./database
COPY public ./public
COPY resources ./resources
COPY routes ./routes
COPY artisan composer.json composer.lock ./
