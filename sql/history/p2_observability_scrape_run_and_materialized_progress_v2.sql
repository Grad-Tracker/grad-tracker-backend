-- Applied migration: p2_observability_scrape_run_and_materialized_progress_v2
-- Purpose: complete P2 observability/audit + materialized progress query support

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create table if not exists public.scrape_runs (
  id bigserial primary key,
  source text not null,
  status text not null default 'started',
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  note text
);

alter table public.scrape_runs enable row level security;

drop policy if exists scrape_runs_select_auth on public.scrape_runs;
create policy scrape_runs_select_auth
on public.scrape_runs
for select
to authenticated
using (true);

drop policy if exists scrape_runs_admin_all on public.scrape_runs;
create policy scrape_runs_admin_all
on public.scrape_runs
for all
to authenticated
using (public.is_admin(auth.uid()))
with check (public.is_admin(auth.uid()));

do $$
declare
  t text;
begin
  foreach t in array array[
    'program_requirement_blocks',
    'program_requirement_courses',
    'program_requirement_block_flags',
    'program_req_sets',
    'program_req_nodes',
    'program_req_atoms'
  ]
  loop
    execute format('alter table public.%I add column if not exists created_at timestamptz not null default now()', t);
    execute format('alter table public.%I add column if not exists updated_at timestamptz not null default now()', t);
    execute format('alter table public.%I add column if not exists scrape_run_id bigint references public.scrape_runs(id)', t);
    execute format('create index if not exists idx_%s_scrape_run_id on public.%I(scrape_run_id)', t, t);

    execute format('drop trigger if exists trg_%s_set_updated_at on public.%I', t, t);
    execute format('create trigger trg_%s_set_updated_at before update on public.%I for each row execute function public.set_updated_at()', t, t);
  end loop;
end $$;

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
  coalesce(sum(mr.missing_course_refs), 0)::bigint as missing_course_refs,
  count(*) filter (where mf.block_id is not null) as manual_blocks
from public.programs p
join block_course_counts bcc on bcc.program_id = p.id
left join manual_flags mf on mf.block_id = bcc.block_id
left join missing_refs mr on mr.block_id = bcc.block_id
group by p.id, p.name
order by p.name;

grant select on public.data_quality to authenticated;

drop materialized view if exists public.student_block_completion_mv;
create materialized view public.student_block_completion_mv as
select *
from public.student_block_completion;

create index if not exists idx_student_block_completion_mv_student_program
  on public.student_block_completion_mv(student_id, program_id, block_id);

create or replace function public.refresh_student_block_completion_mv()
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.is_admin(auth.uid()) then
    raise exception 'Only admins can refresh student_block_completion_mv';
  end if;

  refresh materialized view public.student_block_completion_mv;
end;
$$;

grant execute on function public.refresh_student_block_completion_mv() to authenticated;
