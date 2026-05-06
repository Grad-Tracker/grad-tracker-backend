# Requirement Rules

Author: CJ Shane

This document summarizes how program requirements are represented in the current Grad Tracker schema.

## Core Entities

- `program_requirement_blocks`: human-readable sections for a program.
- `program_requirement_courses`: flat course links attached to a block.
- `program_req_sets`, `program_req_nodes`, and `program_req_atoms`: tree model for nested `AND`/`OR` logic.
- `program_requirement_block_flags`: manual review notes for requirements that cannot be safely automated.

## Rule Meanings

- `ALL_OF`: the student must complete all listed courses in the block.
- `N_OF`: the student must complete at least `n_required` courses from the block.
- `ANY_OF`: flexible choice-like bucket from scraped catalog data.
- `CREDITS_OF`: credits-based requirement; tracked in the schema, but not fully enforced as credit math everywhere.

## Tree Logic

Use the tree tables when requirements cannot be represented as a flat list.

Example:

- Text: `PHYS 201` OR (`CHEM 101` AND `CHEM 103`)
- Root node: `OR`
- Child nodes: `ATOM(PHYS 201)` and `AND`
- Nested children: `ATOM(CHEM 101)` and `ATOM(CHEM 103)`

## Manual Requirements

Some catalog text is intentionally marked manual when it cannot be safely structured.

Examples:

- advisor or department approval
- placement, audition, or standing requirements
- variable special topics
- requirement text without explicit course codes

Manual cases are recorded in `program_requirement_block_flags`, usually with `manual_reason` and `metadata`.

## Completion Source Of Truth

- Student completion comes from `student_course_history.completed = true`.
- Cross-listed equivalence is exposed through `course_equivalents`.
- Program progress is surfaced through `student_block_completion`, `student_block_completion_mv`, and `student_program_summary`.
