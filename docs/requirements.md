# Requirement Rules

This document describes how program requirements are represented and interpreted.

## Core Entities
- `program_requirement_blocks`: human-readable blocks for a program requirement section.
- `program_requirement_courses`: flat course links attached to a block.
- `program_req_sets` / `program_req_nodes` / `program_req_atoms`: tree model for nested logic.

## Rule Meanings
- `ALL_OF`: student must complete all listed courses in the block.
- `N_OF`: student must complete at least `n_required` courses from the block.
- `ANY_OF`: treated as a non-strict recommendation bucket in scraped data.
- `CREDITS_OF`: credits-based requirement; currently tracked but not fully enforced by credit math.

## Tree Logic
Use tree logic when requirements cannot be represented as a flat list.

Example:
- Requirement text: `PHYS 201` OR (`CHEM 101` AND `CHEM 103`)
- Representation:
  - Root node: `OR`
  - Child 1: `ATOM(PHYS 201)`
  - Child 2: `AND`
  - Child 2 children: `ATOM(CHEM 101)`, `ATOM(CHEM 103)`

## Manual Requirements
Some requirement text is intentionally marked manual when it cannot be safely structured.

Examples:
- Standing-based rules (e.g., junior standing)
- Advisor/department approval
- Placement/audition
- Special topics with variable content

These are recorded in `program_requirement_block_flags` with `flag_type = 'MANUAL_REQUIREMENT'`.

## Completion Source of Truth
- Student completion is based on `student_course_history.completed = true`.
- Cross-listed equivalence is applied via `course_equivalents`.
- Program/block outputs are surfaced through:
  - `student_block_completion`
  - `student_program_summary`
