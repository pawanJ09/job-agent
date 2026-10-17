# Build and publish the job-agent Docker image to GitHub Container Registry (ghcr.io).
#
# Usage (from the project root):
#   make help
#   make login GITHUB_USER=yourgithubname
#   make push  GITHUB_USER=yourgithubname VERSION=1.0.0
#
# `make login` asks for a password: use a GitHub personal access token (classic)
# with the write:packages scope. Tip: `export GITHUB_USER=yourgithubname` once per
# terminal session to avoid typing it every time.

GITHUB_USER ?=
REGISTRY    ?= ghcr.io
IMAGE_NAME  ?= job-agent
VERSION     ?= 1.0.0
PLATFORMS   ?= linux/amd64,linux/arm64
BUILDER     ?= job-agent-builder
APP_DIR     := ./app
# ghcr.io only accepts lowercase image names
OWNER       = $(shell echo "$(GITHUB_USER)" | tr '[:upper:]' '[:lower:]')
IMAGE       = $(REGISTRY)/$(OWNER)/$(IMAGE_NAME)

.DEFAULT_GOAL := help
.PHONY: help require-user login build check builder push kit

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-8s %s\n", $$1, $$2}'

require-user:
	@test -n "$(GITHUB_USER)" || { echo "GITHUB_USER is not set. Example: make push GITHUB_USER=yourname"; exit 1; }

login: require-user ## Log in to ghcr.io (password = a GitHub token with write:packages)
	docker login $(REGISTRY) -u $(GITHUB_USER)

build: require-user ## Build the image locally for this machine only (for testing)
	docker build -t $(IMAGE):$(VERSION) $(APP_DIR)

check: build ## Fail if the image contains personal data (resume, session, .env)
	@docker run --rm --entrypoint sh $(IMAGE):$(VERSION) -c 'test ! -e /app/data && test ! -e /app/.env' \
	  || { echo "FAILED: image contains /app/data or /app/.env. Check app/.dockerignore, then rebuild. Not safe to push."; exit 1; }
	@echo "OK: no /app/data or /app/.env inside the image."

builder: ## Create the multi-platform builder if it does not exist yet
	@docker buildx inspect $(BUILDER) >/dev/null 2>&1 || docker buildx create --name $(BUILDER) --driver docker-container

push: check builder ## Build for amd64 + arm64 and push VERSION and latest to ghcr.io
	docker buildx build --builder $(BUILDER) --platform $(PLATFORMS) \
	  -t $(IMAGE):$(VERSION) -t $(IMAGE):latest --push $(APP_DIR)
	@echo "Pushed $(IMAGE):$(VERSION) and $(IMAGE):latest"
	@echo "First push only: the package starts out private. On GitHub, open your profile > Packages > $(IMAGE_NAME) > Package settings, and change visibility to public so others can pull it."

kit: require-user ## Build dist/job-agent-kit.zip (compose file, .env.example, README) to share
	@rm -rf dist/job-agent-kit && mkdir -p dist/job-agent-kit/data dist/job-agent-kit/logs
	@cp kit/docker-compose.yml kit/.env.example kit/README.md dist/job-agent-kit/
	@touch dist/job-agent-kit/data/.gitkeep dist/job-agent-kit/logs/.gitkeep
	@sed -i.bak 's|__IMAGE__|$(IMAGE):$(VERSION)|' dist/job-agent-kit/docker-compose.yml && rm dist/job-agent-kit/docker-compose.yml.bak
	@cd dist && rm -f job-agent-kit.zip && zip -qr job-agent-kit.zip job-agent-kit
	@echo "Created dist/job-agent-kit.zip (image $(IMAGE):$(VERSION))"
