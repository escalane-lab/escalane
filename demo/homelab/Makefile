# Escalane homelab convenience demo (Docker Compose project: home)
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
UV ?= uv

.PHONY: demo demo-live up down flip-unhealthy flip-healthy logs

demo:
	cd $(ROOT) && $(UV) run escalane demo homelab --backend mock --gate-config A3

demo-live: up flip-unhealthy
	cd $(ROOT) && $(UV) run escalane demo homelab --backend mock --gate-config A3 --live-stack

up:
	docker compose -p home up -d --build

down:
	docker compose -p home down -v

flip-unhealthy:
	./scripts/flip_health.sh convenience-app unhealthy

flip-healthy:
	./scripts/flip_health.sh convenience-app healthy

logs:
	docker compose -p home logs -f --tail=50
