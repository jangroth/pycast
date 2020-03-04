.PHONY: help pipenv test deploy

INPUT_TEMPLATE_FILE := pycast.sam.yaml
OUTPUT_TEMPLATE_FILE := .aws-sam/pycast-output.yaml
ARTIFACT_BUCKET := pycast-artifacts
STACK_NAME := pycast
SOURCE_FILES := $(shell find . -type f -path './src/*')
MANIFEST_FILE := ./src/requirements.txt

help: ## This help
	@grep -E -h "^[a-zA-Z_-]+:.*?## " $(MAKEFILE_LIST) \
	  | sort \
	  | awk -v width=36 'BEGIN {FS = ":.*?## "} {printf "\033[36m%-*s\033[0m %s\n", width, $$1, $$2}'

pipenv: ## Install pipenv and dependencies
	pip install pipenv
	pipenv install --dev

test: ## Run linters & tests
	flake8
	yamllint -f parsable .
	cfn-lint -f parseable
	PYTHONPATH=./src pytest --cov=src --cov-report term-missing
	@echo '*** all checks passing ***'

.aws-sam/build/template.yaml: $(INPUT_TEMPLATE_FILE) $(SOURCE_FILES)  ## sam-build target and dependencies
	SAM_CLI_TELEMETRY=0 \
	sam build \
		--template-file $(INPUT_TEMPLATE_FILE) \
		--manifest $(MANIFEST_FILE) \
		--debug
	@echo '*** done building ***'

$(OUTPUT_TEMPLATE_FILE): $(INPUT_TEMPLATE) .aws-sam/build/template.yaml
	SAM_CLI_TELEMETRY=0 \
	sam package \
		--s3-bucket $(ARTIFACT_BUCKET) \
		--output-template-file "$(OUTPUT_TEMPLATE_FILE)" \
		--debug
	@echo '*** done packaging ***'

deploy: $(OUTPUT_TEMPLATE_FILE) ## Deploys to AWS
	SAM_CLI_TELEMETRY=0 \
	sam deploy \
		--template-file $(OUTPUT_TEMPLATE_FILE) \
		--stack-name $(STACK_NAME) \
		--s3-bucket $(ARTIFACT_BUCKET) \
		--capabilities "CAPABILITY_IAM" \
		--no-fail-on-empty-changeset
	@echo '*** done deploying ***'