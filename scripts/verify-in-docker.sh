#!/usr/bin/env bash
# SCMTIPS Field - Verify In Docker Runner (Rule 2.1 / Task R0.7)
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Check if already running inside Docker container
if [ -f "/.dockerenv" ] || [ -n "${CONTAINER_ID}" ]; then
    echo "Running inside Docker container environment..."
    cd "${ROOT_DIR}"
    exec uv run python scripts/verify_all.py "$@"
fi

# Running on host: invoke Docker
if ! command -v docker &> /dev/null; then
    echo "[FAIL] docker command not found. Docker is required to run Linux verification." >&2
    exit 1
fi

IMAGE_TAG="scmtips-field-verify:latest"

echo "Building verification container image: ${IMAGE_TAG}..."
docker build -t "${IMAGE_TAG}" -f "${ROOT_DIR}/deploy/docker/verify.Dockerfile" "${ROOT_DIR}"

echo "Running honest verification suite in Linux Docker container..."
docker run --rm \
    -v "${ROOT_DIR}:/workspace" \
    -v "scmtips-trivy-cache:/root/.cache" \
    -v "scmtips-uv-cache:/root/.cache/uv" \
    -w /workspace \
    "${IMAGE_TAG}" \
    bash -c "uv run python scripts/verify_all.py $*"
