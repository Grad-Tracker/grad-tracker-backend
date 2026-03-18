# Grad Tracker Database Overview

This README explains the Grad Tracker database at a high level: what it stores, how the main tables relate, and how to reason about student progress. It is meant to be detailed but not overly technical.

## What The Database Tracks
- Programs (majors, minors, certificates, graduate programs)
- Courses and their relationships (cross-listings, offerings, prerequisites)
- Program requirements as blocks of rules
- Student course history and progress against program requirements
- Staff and student accounts (with role-based access control)

## Core Tables

### Programs
- `programs`  
  Stores each program and its type (MAJOR, MINOR, CERTIFICATE, GRADUATE).

### Courses
- `courses`  
  The catalog of all courses (subject, number, title, credits).
- `course_crosslistings`  
  Links courses that are equivalent (e.g., CSCI 380 cross-listed with MIS 328).
- `course_offerings`  
  Terms in which a course is offered (one row per course + term).

### Requirements (Blocks + Trees)
- `program_requirement_blocks`  
  Human-readable blocks like “Required Courses” or “Select one of the following.”
- `program_requirement_courses`  
  Flat list of course requirements linked to a block.

Some requirements need richer logic than a flat list. Those are represented in a requirement tree:
- `program_req_sets`  
  Root of the requirement tree for a block.
- `program_req_nodes`  
  Logical nodes (AND, OR, ATOM) that form the tree.
- `program_req_atoms`  
  The actual course references under a node.

This allows patterns like:
- “PHYS 201” OR (“CHEM 101” AND “CHEM 103”)

### Students
- `students`  
  Student profile data linked to auth users.
- `student_course_history`  
  Courses taken by students, with completion status and term.

### Staff
- `staff`  
  Staff members with an `is_admin` flag for elevated access.

## How Progress Is Computed
- `student_block_completion` (view)  
  Shows completion status for each requirement block per student.
- `student_program_summary` (view)  
  Summarizes how many blocks are complete vs. manual/unknown.

Rules used:
- Course completion is based on `student_course_history.completed = true`.
- Cross-listed courses are treated as equivalent.
- Blocks with unclear or non-explicit requirements are marked MANUAL.

## Data Quality & Scraping
Program requirements are scraped from the catalog. The scrapers:
- Create requirement blocks and course links
- Detect “select N” or “choose one” logic
- Record manual/unknown requirements when text is not explicit
- Output reports for missing courses and skipped lines

## Access Control (RLS)
Row-level security is enabled on public tables. Policies follow these rules:
- Regular users can access only their own rows (by `auth_user_id`)
- Admin staff can access and edit all tables
- Records without `auth_user_id` are not accessible

## Typical Questions This Schema Answers
- What courses are required for a program?
- Which requirement blocks are complete for a given student?
- Which courses are offered in which terms?
- Are two courses equivalent (cross-listed)?

## Where To Look Next
- `DATABASE_CHANGES.md` for technical history
- `DATABASE_CHANGES_BY_JIRA.md` for change tracking by ticket
- `DATABASE_HARDENING_TODOS.md` for cleanup and validation work
