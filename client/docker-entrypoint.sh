#!/bin/sh
# The node_modules volume keeps the first image install. Reinstall when the
# mounted lockfile no longer matches that install. npm ci deletes
# node_modules, which fails when that path is a mount, so the install
# happens in a temporary directory and is copied into the volume.
set -eu
hash=$(sha256sum package-lock.json | awk '{print $1}')
stamp=node_modules/.package-lock.sha256
if [ ! -f "$stamp" ] || [ "$(cat "$stamp")" != "$hash" ]; then
  stage=$(mktemp -d)
  cp package.json package-lock.json "$stage/"
  if [ -f .npmrc ]; then
    cp .npmrc "$stage/"
  fi
  (cd "$stage" && npm ci)
  mkdir -p node_modules
  find node_modules -mindepth 1 -delete
  cp -a "$stage/node_modules/." node_modules/
  rm -rf "$stage"
  echo "$hash" > node_modules/.package-lock.sha256
fi
exec npm run dev -- --host 0.0.0.0 --port 5173
