# Agentic SDLC & Spec-Driven Development (A3 Coaching)

This project uses the A3 standard process and AI to transform coaching cases into knowledge assets.

## Document-First SOP
Adhere to a documentation-centric workflow to ensure consistency across the monorepo:

- **Single Source of Truth**: Authority: `docs/*.md` > `.kiro/specs/` > `.kiro/steering/` > Existing Code.
- **Pre-coding Dry Run**: Before implementation, output a report covering:
  - **Impact Scope**: Affected files and modules.
  - **Alignment Check**: Consistency with design, contracts, and requirements.
  - **Decision**: Request deviation approval or confirm design adherence.
- **Post-coding Deviation**: If implementation diverges, generate a record using `.kiro/settings/templates/deviation-record-template.md` and save it to `docs/deviation/`.

## Project Structure
- **Paths**: Steering: `.kiro/steering/` | Specs: `.kiro/specs/`
- **Monorepo**: Backend (`/backend`), Frontend (`/frontend`), Shared Docs (`/docs`).

## Development Guidelines
- **Language**: Think in English; generate responses and project files in Simplified Chinese.
- **3-Phase Approval**: Requirements → Design → Tasks → Implementation.
- **Autonomy**: Follow instructions precisely; act autonomously; ask only if information is missing.
- **Skills**: Invoke relevant skills in `.claude/skills/` if there is even a 1% chance they apply.

## Minimal Workflow
- **Discovery**: `/kiro-discovery "idea"` (Writes brief.md and roadmap.md).
- **Phase 1 (Specification)**:
  - Quick Start: `/kiro-spec-quick {feature} [--auto]`
  - Manual: `/kiro-spec-init` -> `/kiro-spec-requirements` -> `/kiro-spec-design` -> `/kiro-spec-tasks`
  - Multi-spec: `/kiro-spec-batch` (Parallel creation via roadmap.md).
- **Phase 2 (Implementation)**: 
  - `/kiro-impl {feature} [tasks]` (Autonomous or manual mode).
  - `/kiro-validate-impl {feature}` (Final validation gate).
- **Status**: `/kiro-spec-status {feature}` (Progress check).

## Critical Protocols
- `kiro-review`: Adversarial review for tasks.
- `kiro-debug`: Root-cause-first debugging.
- `kiro-verify-completion`: Fresh-evidence gate before success claims.

## Design Review Principles
- **Issue Filter**: Each finding must answer: Does it block core business? Would it occur in production? Must it be resolved at design phase? Is it a logic confusion? Is it a critical non-detail issue? If all answers are no, it is not an issue.
- **Document Coupling**: When suggesting changes, assess whether `requirements.md`, `design.md`, `tasks.md`, `research.md` also need updates — do not target `design.md` alone.

## Python Readability Execution Guard
- For backend Python implementation, run readability checks before claiming completion:
  - `ruff check backend`
  - `python scripts/readability_check.py --path backend --max-lines 100`
- CI integration is optional and not required by default at this stage.
