# Database + FERPA Audit Report

Author: CJ Shane
Status: Historical audit record; use current database docs for active workflow.

Date: 2026-03-17
Target: Supabase Postgres (`public` + auth-adjacent access surface)
Method: MCP metadata inspection (`list_tables`, `get_advisors`, `execute_sql` policy/grant/function analysis)

## Severity Scale
- Critical: Immediate risk of unauthorized disclosure/modification of education records.
- High: Strong likelihood of FERPA control failure under realistic misuse.
- Medium: Material control weakness that increases breach/compliance risk.
- Low: Hardening/performance gap with secondary security impact.

## Executive Summary
The database has strong building blocks (RLS enabled on all `public` base tables, ownership-style policies for student rows), but it is currently undermined by very broad default grants and several elevated objects exposed to low-trust roles. The current privilege posture is inconsistent with FERPA least-privilege expectations.

Most urgent: remove blanket `anon`/`authenticated` default privileges and tighten execution/select exposure on derived objects and security-definer paths.

## Findings

### 1) Blanket default ACL grants give `anon` and `authenticated` broad rights on new objects
Severity: Critical

Evidence:
- `pg_default_acl` in `public` grants:
  - tables: `anon=arwdDxtm`, `authenticated=arwdDxtm`
  - functions: `anon=X`, `authenticated=X`
  - sequences: `anon=rwU`, `authenticated=rwU`

Why this matters (FERPA):
- FERPA requires strict access controls to education records.
- A permissive default ACL means every newly created table/function/sequence is immediately exposed unless explicitly locked down, making accidental record disclosure/modification likely.

Required improvement:
- Replace default ACLs with deny-by-default.
- Grant only object-specific privileges required by API paths.
- Add migration guardrails (CI check) that fail on permissive ACL regressions.

---

### 2) Sensitive student objects are broadly granted at object level to `anon` and `authenticated`
Severity: Critical

Evidence:
- `information_schema.role_table_grants` shows `DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE` for `anon` and `authenticated` across student objects including:
  - `public.students`
  - `public.student_course_history`
  - `public.student_planned_courses`
  - `public.student_programs`
  - derived student views (`student_program_summary`, `student_block_completion`)
- `has_table_privilege('anon', 'public.students', 'select') = true` (and similar for student-derived objects).

Why this matters (FERPA):
- RLS is the final guard, but broad grants massively increase blast radius for any policy mistake or future migration drift.
- FERPA programs should keep both grants and row policies least-privileged; this setup currently relies too heavily on RLS alone.

Required improvement:
- Revoke all non-essential DML/DDL-ish rights from `anon` and `authenticated`.
- Use minimal grants (`SELECT` only where explicitly needed; no `TRUNCATE`, `TRIGGER`, `REFERENCES` for client roles).

---

### 3) `public` role DELETE policies exist on student-record tables
Severity: High

Evidence (`pg_policies`):
- `student_course_history`: `Users can delete own course history` with roles `{public}`
- `student_planned_courses`: `Users can delete own planned courses` with roles `{public}`
- `student_programs`: `Delete courses`, `Users can delete own programs` with roles `{public}`

Why this matters (FERPA):
- Policies on `{public}` include unauthenticated callers; while `auth.uid()` often blocks null sessions, this is still an unnecessary exposure path and policy-complexity hazard.
- Student record deletions should require explicit authenticated role checks and auditable intent.

Required improvement:
- Move these policies to `{authenticated}` only.
- Add explicit `auth.uid() is not null` checks where user context is required.

---

### 4) Security-definer view is externally exposed
Severity: High

Evidence (advisor):
- `public.course_equivalents` flagged as `security_definer_view`.

Why this matters (FERPA):
- Security-definer views execute under creator privilege and can bypass expected caller restrictions.
- FERPA control design expects caller-scoped authorization, not owner-scoped escalation.

Required improvement:
- Recreate as security-invoker (or equivalent safe pattern), or replace with table/function pattern with explicit checks.
- Re-verify no derived view can bypass intended RLS boundaries.

---

### 5) Materialized view with student completion data is API-accessible
Severity: High

Evidence:
- Advisor warning: `public.student_block_completion_mv` selectable by `anon`/`authenticated`.
- `has_table_privilege` confirms selectable by both roles.
- Contains `student_id` + completion status fields.

Why this matters (FERPA):
- Materialized views store snapshot data and are not protected by base-table RLS semantics in the same way as policy-governed tables.
- Exposing student progress snapshots to broad roles risks unauthorized disclosure of education records.

Required improvement:
- Revoke direct API role access.
- Serve this data through controlled security-definer RPC with strict authz checks, or per-user filtered view strategy.

---

### 6) Security-definer function with write side effects is executable by low-trust roles
Severity: High

Evidence:
- `public.run_nightly_data_quality_job()` is `SECURITY DEFINER` and executable by `anon` and `authenticated`.
- Function inserts rows into `public.nightly_data_quality_runs` and has no caller-role check.

Why this matters (FERPA):
- Even if table is not FERPA data, unauthenticated invocation of privileged write paths is a control failure and can be abused for resource consumption, noise, and operational integrity issues.

Required improvement:
- Revoke execute from `anon`/`authenticated`.
- Restrict to service role or admin-only wrapper with explicit authorization gate.

---

### 7) Security-definer function callable by low-trust roles creates avoidable abuse surface
Severity: Medium

Evidence:
- `public.refresh_student_block_completion_mv()` executable by `anon` and `authenticated`.
- It checks `is_admin(auth.uid())` before refresh, but still allows untrusted invocation attempts.

Why this matters (FERPA):
- Not a direct disclosure vector due in-function check, but it expands attack/noise surface and complicates auditability.

Required improvement:
- Revoke execute from non-admin roles.
- Keep only explicit admin/service execution paths.

---

### 8) Function search_path hardening gap
Severity: Medium

Evidence (advisor):
- `public.set_updated_at` has mutable `search_path` (no fixed `SET search_path`).

Why this matters (FERPA):
- Mutable search path can enable function-hijack patterns in misconfigured environments.
- FERPA environments should enforce deterministic function resolution.

Required improvement:
- Recreate function with explicit `SET search_path TO public` (or locked schema list).

---

### 9) Leaked password protection is disabled
Severity: Medium

Evidence (advisor):
- `auth_leaked_password_protection` warning.

Why this matters (FERPA):
- Credential compromise is a primary root cause of unauthorized student-record access.

Required improvement:
- Enable leaked password checks and enforce stronger password policy controls.

---

### 10) RLS is enabled but not forced (`FORCE ROW LEVEL SECURITY` absent)
Severity: Medium

Evidence:
- All `public` base tables: `rls_enabled=true`, `rls_forced=false`.

Why this matters (FERPA):
- Table owners and certain privileged contexts can bypass RLS unless forced, increasing insider/configuration risk.

Required improvement:
- Evaluate `ALTER TABLE ... FORCE ROW LEVEL SECURITY` for FERPA-scoped tables.
- Pair with service-path review so legitimate backend jobs still function safely.

---

### 11) Auditability gap for FERPA-grade access tracing
Severity: Medium

Evidence:
- No installed `pgaudit` extension in this project snapshot.
- Existing auth audit logs cover authentication events, not full data-access audit trail for educational records.

Why this matters (FERPA):
- Institutions need traceable, reviewable access history for education records and incident response.

Required improvement:
- Implement database/data-api access logging strategy for student-record reads/writes.
- Centralize immutable audit logs with retention policy and periodic review.

---

### 12) Performance findings that can degrade policy behavior under load
Severity: Low

Evidence (advisor):
- Multiple unindexed foreign keys.
- Duplicate indexes.
- `auth_rls_initplan` warnings (policy expressions repeatedly calling auth/context functions).
- Multiple permissive policies for same role/action across many tables.

Why this matters:
- Performance degradation increases operational risk and can incentivize unsafe shortcuts (e.g., bypassing policy-heavy paths).

Required improvement:
- Add missing FK indexes.
- Remove duplicate indexes.
- Refactor RLS expressions to `(select auth.uid())` style patterns.
- Consolidate overlapping permissive policies where feasible.

## Positive Controls Observed
- RLS is enabled on all `public` base tables inspected.
- Student ownership model is present (`students.auth_user_id` and ownership checks in many policies).
- Key authorization helper functions (`is_admin`, `is_advisor`, `is_advisor_for_program`) are security-definer with fixed `search_path`.

## Prioritized Remediation Plan
1. Immediately fix ACL posture (Critical): default ACL lockdown + revoke broad grants from `anon`/`authenticated`.
2. Lock down student-derived objects (Critical/High): revoke direct access to student views/materialized views unless explicitly required.
3. Remove `{public}` role from student-table mutation policies (High).
4. Restrict execution on privileged functions to admin/service paths (High/Medium).
5. Resolve advisor security warnings (`security_definer_view`, mutable search path, leaked password protection) (High/Medium).
6. Add FERPA-grade access logging and review process (Medium).
7. Complete performance hardening backlog (Low).

## Scope Notes
- This audit is based on live metadata/policies/grants and advisor lints available through MCP at audit time.
- Application-layer controls (API gateway checks, client key handling, business-process consent workflows, institutional FERPA procedures) were not directly inspected here and should be audited separately.
