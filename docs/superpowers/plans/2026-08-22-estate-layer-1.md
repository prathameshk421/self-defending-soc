# Layer 1 Estate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver a versioned, queryable lab asset catalog (Estate) plus agent working files.

**Architecture:** YAML inventory → fail-closed loader → in-process `Estate` query API → CLI. No HTTP, DB, or execute methods in Layer 1.

**Tech Stack:** Python 3.12+, Pydantic v2, PyYAML, pytest.

See the approved plan and repo files under `src/estate/`, `inventory/default.yaml`, `AGENTS.md`.
