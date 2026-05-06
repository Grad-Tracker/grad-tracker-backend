-- Stage 0 baseline snapshot queries for FERPA remediation.
-- Run before and after remediation to compare grants, policies, and exposure.

-- Default ACL posture
select
  defaclrole::regrole::text as grantor,
  defaclnamespace::regnamespace::text as schema_name,
  defaclobjtype as objtype,
  coalesce(array_to_string(defaclacl, ','), '') as acl
from pg_default_acl
where defaclnamespace = 'public'::regnamespace
order by grantor, objtype;

-- Table/view/materialized view privileges for low-trust roles
select
  table_schema,
  table_name,
  grantee,
  string_agg(privilege_type, ',' order by privilege_type) as privileges
from information_schema.role_table_grants
where table_schema = 'public'
  and grantee in ('anon','authenticated','service_role')
group by table_schema, table_name, grantee
order by table_name, grantee;

-- Function execute grants for security-sensitive functions
select
  p.proname,
  pg_get_function_identity_arguments(p.oid) as args,
  p.prosecdef as security_definer,
  coalesce(string_agg(distinct rp.grantee, ',' order by rp.grantee), '') as execute_grantees
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
left join information_schema.routine_privileges rp
  on rp.routine_schema = n.nspname
 and rp.routine_name = p.proname
where n.nspname = 'public'
  and p.proname in (
    'run_nightly_data_quality_job',
    'refresh_student_block_completion_mv',
    'set_updated_at',
    'is_admin',
    'is_advisor',
    'is_advisor_for_program'
  )
group by p.proname, p.oid, p.prosecdef
order by p.proname;

-- FERPA table policies
select
  schemaname,
  tablename,
  policyname,
  roles,
  cmd,
  qual,
  with_check
from pg_policies
where schemaname = 'public'
  and tablename in (
    'students',
    'student_course_history',
    'student_planned_courses',
    'student_programs',
    'student_term_plan',
    'plans',
    'plan_programs'
  )
order by tablename, cmd, policyname;

-- RLS force status on FERPA tables
select
  c.relname as table_name,
  c.relrowsecurity as rls_enabled,
  c.relforcerowsecurity as rls_forced
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relkind = 'r'
  and c.relname in (
    'students',
    'student_course_history',
    'student_planned_courses',
    'student_programs',
    'student_term_plan',
    'plans',
    'plan_programs'
  )
order by c.relname;

-- Security lint hotspots
select
  c.relname,
  c.relkind,
  c.reloptions
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relname in ('course_equivalents','student_block_completion_mv');
