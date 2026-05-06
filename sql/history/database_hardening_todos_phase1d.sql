-- Applied migration: database_hardening_todos_phase1d
-- Purpose: implement high-priority hardening tasks from DATABASE_HARDENING_TODOS.md

create or replace function public.is_admin(uid uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.staff s
    where s.auth_user_id = uid
      and s.is_admin = true
  );
$$;

grant execute on function public.is_admin(uuid) to authenticated;

drop policy if exists staff_select_own on public.staff;
drop policy if exists staff_insert_own on public.staff;
drop policy if exists staff_update_own on public.staff;
drop policy if exists staff_delete_own on public.staff;

create policy staff_select_own
on public.staff
for select
to authenticated
using (
  auth.uid() is not null
  and auth_user_id is not null
  and (auth.uid() = auth_user_id or public.is_admin(auth.uid()))
);

create policy staff_insert_own
on public.staff
for insert
to authenticated
with check (
  auth.uid() is not null
  and auth_user_id is not null
  and (auth.uid() = auth_user_id or public.is_admin(auth.uid()))
);

create policy staff_update_own
on public.staff
for update
to authenticated
using (
  auth.uid() is not null
  and auth_user_id is not null
  and (auth.uid() = auth_user_id or public.is_admin(auth.uid()))
)
with check (
  auth.uid() is not null
  and auth_user_id is not null
  and (auth.uid() = auth_user_id or public.is_admin(auth.uid()))
);

create policy staff_delete_own
on public.staff
for delete
to authenticated
using (
  auth.uid() is not null
  and auth_user_id is not null
  and (auth.uid() = auth_user_id or public.is_admin(auth.uid()))
);

drop policy if exists students_select_own on public.students;
drop policy if exists students_insert_own on public.students;
drop policy if exists students_update_own on public.students;
drop policy if exists students_delete_own on public.students;

create policy students_select_own
on public.students
for select
to authenticated
using (
  auth.uid() is not null
  and auth_user_id is not null
  and (auth.uid() = auth_user_id or public.is_admin(auth.uid()))
);

create policy students_insert_own
on public.students
for insert
to authenticated
with check (
  auth.uid() is not null
  and auth_user_id is not null
  and (auth.uid() = auth_user_id or public.is_admin(auth.uid()))
);

create policy students_update_own
on public.students
for update
to authenticated
using (
  auth.uid() is not null
  and auth_user_id is not null
  and (auth.uid() = auth_user_id or public.is_admin(auth.uid()))
)
with check (
  auth.uid() is not null
  and auth_user_id is not null
  and (auth.uid() = auth_user_id or public.is_admin(auth.uid()))
);

create policy students_delete_own
on public.students
for delete
to authenticated
using (
  auth.uid() is not null
  and auth_user_id is not null
  and (auth.uid() = auth_user_id or public.is_admin(auth.uid()))
);

drop policy if exists "Authenticated users can insert terms" on public.terms;

drop policy if exists program_requirement_block_flags_admin_all on public.program_requirement_block_flags;
create policy program_requirement_block_flags_admin_all
on public.program_requirement_block_flags
for all
to authenticated
using (public.is_admin(auth.uid()))
with check (public.is_admin(auth.uid()));

alter view if exists public.student_block_completion set (security_invoker = true, security_barrier = true);
alter view if exists public.student_program_summary set (security_invoker = true, security_barrier = true);

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname='program_requirement_blocks_n_required_positive_chk'
      and connamespace='public'::regnamespace
  ) then
    alter table public.program_requirement_blocks
      add constraint program_requirement_blocks_n_required_positive_chk
      check (n_required is null or n_required > 0);
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname='program_requirement_blocks_credits_non_negative_chk'
      and connamespace='public'::regnamespace
  ) then
    alter table public.program_requirement_blocks
      add constraint program_requirement_blocks_credits_non_negative_chk
      check (credits_required is null or credits_required >= 0);
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname='courses_credits_non_negative_chk'
      and connamespace='public'::regnamespace
  ) then
    alter table public.courses
      add constraint courses_credits_non_negative_chk
      check (credits >= 0);
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname='courses_subject_upper_alpha_chk'
      and connamespace='public'::regnamespace
  ) then
    alter table public.courses
      add constraint courses_subject_upper_alpha_chk
      check (subject ~ '^[A-Z]{2,10}$');
  end if;
end $$;

alter table public.student_course_history
  alter column completed set default false;

update public.student_course_history
set completed = false
where completed is null;

create index if not exists idx_program_requirement_courses_course_id
  on public.program_requirement_courses(course_id);

create index if not exists idx_student_course_history_student_id
  on public.student_course_history(student_id);

create index if not exists idx_student_course_history_course_id
  on public.student_course_history(course_id);

create index if not exists idx_course_crosslistings_course_id
  on public.course_crosslistings(course_id);

create table if not exists public.course_code_aliases (
  id bigserial primary key,
  subject text not null,
  number text not null,
  course_id bigint not null references public.courses(id) on delete cascade,
  created_at timestamptz not null default now(),
  unique(subject, number)
);

alter table public.course_code_aliases enable row level security;

drop policy if exists course_code_aliases_select_auth on public.course_code_aliases;
create policy course_code_aliases_select_auth
on public.course_code_aliases
for select
to authenticated
using (true);

drop policy if exists course_code_aliases_admin_all on public.course_code_aliases;
create policy course_code_aliases_admin_all
on public.course_code_aliases
for all
to authenticated
using (public.is_admin(auth.uid()))
with check (public.is_admin(auth.uid()));

create or replace view public.data_quality
with (security_invoker = true, security_barrier = true)
as
with block_course_counts as (
  select b.id as block_id, b.program_id, count(prc.course_id) as required_count
  from public.program_requirement_blocks b
  left join public.program_requirement_courses prc on prc.block_id = b.id
  group by b.id, b.program_id
),
manual_flags as (
  select distinct block_id
  from public.program_requirement_block_flags
  where flag_type = 'MANUAL_REQUIREMENT'
),
missing_refs as (
  select prc.block_id, count(*) as missing_course_refs
  from public.program_requirement_courses prc
  left join public.courses c on c.id = prc.course_id
  where c.id is null
  group by prc.block_id
)
select
  p.id as program_id,
  p.name as program_name,
  count(*) filter (where bcc.required_count = 0) as empty_blocks,
  count(*) filter (where bcc.required_count > 0) as non_empty_blocks,
  count(*) filter (where bcc.required_count = 0 and mf.block_id is not null) as manual_empty_blocks,
  coalesce(sum(mr.missing_course_refs), 0)::bigint as missing_course_refs
from public.programs p
join block_course_counts bcc on bcc.program_id = p.id
left join manual_flags mf on mf.block_id = bcc.block_id
left join missing_refs mr on mr.block_id = bcc.block_id
group by p.id, p.name
order by p.name;

grant select on public.data_quality to authenticated;
