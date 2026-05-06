-- Applied migration: p0_remaining_security_and_checks_cleanup
-- Purpose: finish remaining enforceable P0 security/check gaps

alter table public.staff
  alter column auth_user_id set not null;

drop policy if exists admin_update_all on public.plan_programs;
create policy admin_update_all
on public.plan_programs
for update
to authenticated
using (public.is_admin(auth.uid()))
with check (public.is_admin(auth.uid()));

drop policy if exists admin_select_all on public.program_req_sets;
create policy admin_select_all
on public.program_req_sets
for select
to authenticated
using (public.is_admin(auth.uid()));

drop policy if exists admin_select_all on public.program_req_nodes;
create policy admin_select_all
on public.program_req_nodes
for select
to authenticated
using (public.is_admin(auth.uid()));

drop policy if exists admin_select_all on public.program_req_atoms;
create policy admin_select_all
on public.program_req_atoms
for select
to authenticated
using (public.is_admin(auth.uid()));

update public.program_requirement_blocks
set credits_required = null
where credits_required is not null
  and credits_required <= 0;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname='program_requirement_blocks_rule_chk'
      and connamespace='public'::regnamespace
  ) then
    alter table public.program_requirement_blocks
      add constraint program_requirement_blocks_rule_chk
      check (rule in ('ALL_OF','N_OF','CREDITS_OF'));
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname='program_requirement_blocks_credits_positive_chk'
      and connamespace='public'::regnamespace
  ) then
    alter table public.program_requirement_blocks
      add constraint program_requirement_blocks_credits_positive_chk
      check (credits_required is null or credits_required > 0);
  end if;
end $$;

alter table public.terms
  add column if not exists code text generated always as (
    year::text || case season
      when 'Spring' then 'SP'
      when 'Summer' then 'SU'
      when 'Fall' then 'FA'
      else '??'
    end
  ) stored;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname='terms_code_format_chk'
      and connamespace='public'::regnamespace
  ) then
    alter table public.terms
      add constraint terms_code_format_chk
      check (code ~ '^[0-9]{4}(SP|SU|FA|WI)$');
  end if;
end $$;

create unique index if not exists uq_course_crosslistings_course_crosslisted
  on public.course_crosslistings(course_id, crosslisted_course_id)
  where crosslisted_course_id is not null;

create unique index if not exists uq_program_req_atoms_node_course
  on public.program_req_atoms(node_id, required_course_id);
