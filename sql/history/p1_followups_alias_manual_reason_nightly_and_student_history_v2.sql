-- Applied migration: p1_followups_alias_manual_reason_nightly_and_student_history_v2
-- Purpose: complete P1 follow-ups for manual flags, nightly quality runs, and student history quality

alter table public.program_requirement_block_flags
  add column if not exists manual_reason text;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname='program_requirement_block_flags_manual_reason_chk'
      and connamespace='public'::regnamespace
  ) then
    alter table public.program_requirement_block_flags
      add constraint program_requirement_block_flags_manual_reason_chk
      check (manual_reason is null or manual_reason in ('credits_only','non_explicit','special_topics'));
  end if;
end $$;

alter table public.student_course_history
  add column if not exists credits_override numeric(6,2);

with term_targets as (
  select
    max(case when season='Spring' and year=2026 then id end) as spring_id,
    max(case when season='Fall' and year=2026 then id end) as fall_id
  from public.terms
)
update public.student_course_history sch
set term_id = case when random() < 0.5 then tt.spring_id else tt.fall_id end
from term_targets tt
where sch.term_id is null
  and tt.spring_id is not null
  and tt.fall_id is not null;

alter table public.student_course_history
  alter column term_id set not null;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname='student_course_history_grade_chk'
      and connamespace='public'::regnamespace
  ) then
    alter table public.student_course_history
      add constraint student_course_history_grade_chk
      check (
        grade is null
        or upper(grade) in ('A','A-','B+','B','B-','C+','C','C-','D+','D','D-','F','P','NP','S','U','W','I')
      );
  end if;
end $$;

alter table public.student_course_history
  drop constraint if exists student_course_history_pkey;
alter table public.student_course_history
  drop constraint if exists uq_student_course;

alter table public.student_course_history
  add constraint student_course_history_pkey primary key (student_id, course_id, term_id);

create index if not exists idx_student_course_history_student_course
  on public.student_course_history(student_id, course_id);

create table if not exists public.nightly_data_quality_runs (
  id bigserial primary key,
  run_at timestamptz not null default now(),
  empty_blocks bigint not null,
  n_of_missing_n bigint not null,
  missing_course_refs bigint not null
);

alter table public.nightly_data_quality_runs enable row level security;

drop policy if exists nightly_data_quality_runs_select_auth on public.nightly_data_quality_runs;
create policy nightly_data_quality_runs_select_auth
on public.nightly_data_quality_runs
for select
to authenticated
using (true);

drop policy if exists nightly_data_quality_runs_admin_all on public.nightly_data_quality_runs;
create policy nightly_data_quality_runs_admin_all
on public.nightly_data_quality_runs
for all
to authenticated
using (public.is_admin(auth.uid()))
with check (public.is_admin(auth.uid()));

create or replace function public.run_nightly_data_quality_job()
returns bigint
language plpgsql
security definer
set search_path = public
as $$
declare
  v_empty_blocks bigint;
  v_n_of_missing_n bigint;
  v_missing_course_refs bigint;
  v_id bigint;
begin
  select count(*) into v_empty_blocks
  from (
    select b.id
    from public.program_requirement_blocks b
    left join public.program_requirement_courses prc on prc.block_id=b.id
    group by b.id
    having count(prc.course_id)=0
  ) t;

  select count(*) into v_n_of_missing_n
  from public.program_requirement_blocks
  where rule='N_OF' and n_required is null;

  select count(*) into v_missing_course_refs
  from public.program_requirement_courses prc
  left join public.courses c on c.id = prc.course_id
  where c.id is null;

  insert into public.nightly_data_quality_runs(empty_blocks, n_of_missing_n, missing_course_refs)
  values (v_empty_blocks, v_n_of_missing_n, v_missing_course_refs)
  returning id into v_id;

  return v_id;
end;
$$;

grant execute on function public.run_nightly_data_quality_job() to authenticated;
