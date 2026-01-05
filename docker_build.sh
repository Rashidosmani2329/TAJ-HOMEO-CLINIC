#!/usr/bin/env bash
set -euo pipefail

# Docker-based Buildozer runner for TajHomeo
# Requirements: Docker installed and running on your machine.
# Usage (from project root):
#   chmod +x docker_build.sh
#   ./docker_build.sh

IMAGE=kivy/buildozer:latest
HOST_DIR="$(pwd)"
CACHE_DIR="$HOME/.buildozer"
mkdir -p "$CACHE_DIR"

echo "Pulling image $IMAGE (may take a while)..."
docker pull $IMAGE

echo "Running Buildozer inside container..."
# Pass UID/GID to avoid root-owned files; mount project and buildozer cache
docker run --rm \
  -v "$HOST_DIR":/home/user/hostcwd \
  -v "$CACHE_DIR":/home/user/.buildozer \
  -e LOCAL_UID=$(id -u) -e LOCAL_GID=$(id -g) \
  -w /home/user/hostcwd \
  $IMAGE buildozer android debug -v

echo "Build finished. If successful, APK will be in ./bin/ on the host." 

# optionally list APK
ls -l ./bin/*.apk || echo "No APK found in ./bin/ yet." 
