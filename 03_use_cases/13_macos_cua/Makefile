SWIFT ?= swift
PRODUCT := metacua
CONFIG ?= debug
SWIFT_FLAGS ?=
ARGS ?=

.PHONY: help build release run agent pointer permissions configure demo bin format fmt lint check clean

help:
	@printf '%s\n' 'metacua Makefile targets'
	@printf '%s\n' ''
	@printf '%s\n' '  make build                         Build debug'
	@printf '%s\n' '  make release                       Build release'
	@printf '%s\n' '  make run ARGS="--help"             Run metacua with optional args; overlay is on by default'
	@printf '%s\n' '  make agent ARGS="--goal ... "      Run metacua agent'
	@printf '%s\n' '  make pointer ARGS="--step 20"      Run keyboard pointer mode'
	@printf '%s\n' '  make permissions ARGS="--prompt"   Check/request macOS permissions'
	@printf '%s\n' '  make configure ARGS="--api-key ..." Save config'
	@printf '%s\n' '  make demo                           Run overlay demo'
	@printf '%s\n' '  make bin                            Print release binary path'
	@printf '%s\n' '  make format                         Format Swift sources'
	@printf '%s\n' '  make lint                           Run swift-format strict lint'
	@printf '%s\n' '  make check                          Lint, debug build, release build'
	@printf '%s\n' '  make clean                          Clean SwiftPM build artifacts'
	@printf '%s\n' ''
	@printf '%s\n' 'Variables: CONFIG=debug|release, SWIFT_FLAGS=..., ARGS=...'

build:
	$(SWIFT) build -c debug $(SWIFT_FLAGS)

release:
	$(SWIFT) build -c release $(SWIFT_FLAGS)

run:
	$(SWIFT) run -c $(CONFIG) $(SWIFT_FLAGS) $(PRODUCT) $(ARGS)

agent:
	$(SWIFT) run -c $(CONFIG) $(SWIFT_FLAGS) $(PRODUCT) agent $(ARGS)

pointer:
	$(SWIFT) run -c $(CONFIG) $(SWIFT_FLAGS) $(PRODUCT) pointer $(ARGS)

permissions:
	$(SWIFT) run -c $(CONFIG) $(SWIFT_FLAGS) $(PRODUCT) permissions $(ARGS)

configure:
	$(SWIFT) run -c $(CONFIG) $(SWIFT_FLAGS) $(PRODUCT) configure $(ARGS)

demo:
	$(SWIFT) run -c $(CONFIG) $(SWIFT_FLAGS) $(PRODUCT) demo $(ARGS)

bin:
	@printf '%s/%s\n' "$$($(SWIFT) build -c release $(SWIFT_FLAGS) --show-bin-path)" "$(PRODUCT)"

format:
	xcrun swift-format format --in-place --recursive Package.swift src

fmt: format

lint:
	xcrun swift-format lint --recursive --strict Package.swift src

check: lint build release

clean:
	$(SWIFT) package clean
