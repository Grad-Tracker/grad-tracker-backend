-- Migration: persist_student_breadth_package_id
-- Purpose: Persist planner breadth package selection in students table.

alter table public.students
  add column if not exists breadth_package_id text default null;

-- Constrain to known package ids (nullable allowed)
do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'chk_students_breadth_package_id'
      and connamespace = 'public'::regnamespace
  ) then
    alter table public.students
      add constraint chk_students_breadth_package_id
      check (
        breadth_package_id is null or breadth_package_id in (
          'math', 'math-physics', 'chemistry', 'project-mgmt',
          'business', 'economics', 'geography', 'criminal-justice',
          'art-design'
        )
      );
  end if;
end $$;
