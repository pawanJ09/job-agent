# Build and publish the job-agent Docker image.
#
# Usage (from the project root):
#   make help
#   make push DOCKER_USER=yourdockerhubname VERSION=1.0.0
#
# Tip: run `export DOCKER_USER=yourdockerhubname` once per terminal session to
# avoid typing it every time.

DOCKER_USER ?=
IMAGE_NAME  ?= job-agent
VERSION     ?= 1.0.0
PLATFORMS   ?= linux/amd64,linux/arm64
BUILDER     ?= job-agent-builder
APP_DIR     := ./app
IMAGE       = $(DOCKER_USER)/$(IMAGE_NAME)

.DEFAULT_GOAL := help
.PHONY: help require-user login build check builder push

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-8s %s\n", $$1, $$2}'

require-user:
	@test -n "$(DOCKER_USER)" || { echo "DOCKER_USER is not set. Example: make push DOCKER_USER=yourname"; exit 1; }

login: require-user ## Log in to Docker Hub (use an access token as the password)
	docker login -u $(DOCKER_USER)

build: require-user ## Build the image locally for this machine only (for testing)
	docker build -t $(IMAGE):$(VERSION) $(APP_DIR)

check: build ## Fail if the image contains personal data (resume, session, .env)
	@docker run --rm --entrypoint sh $(IMAGE):$(VERSION) -c 'test ! -e /app/data && test ! -e /app/.env' \
	  || { echo "FAILED: image contains /app/data or /app/.env. Check app/.dockerignore, then rebuild. Not safe to push."; exit 1; }
	@echo "OK: no /app/data or /app/.env inside the image."

builder: ## Create the multi-platform builder if it does not exist yet
	@docker buildx inspect $(BUILDER) >/dev/null 2>&1 || docker buildx create --name $(BUILDER) --driver docker-container

push: check builder ## Build for amd64 + arm64 and push VERSION and latest to Docker Hub
	docker buildx build --builder $(BUILDER) --platform $(PLATFORMS) \
	  -t $(IMAGE):$(VERSION) -t $(IMAGE):latest --push $(APP_DIR)
	@echo "Pushed $(IMAGE):$(VERSION) and $(IMAGE):latest"
