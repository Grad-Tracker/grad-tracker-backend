-- Applied migration: p0_backcompat_constraints_course_number_and_course_offerings_term_id
-- Purpose: enforce strict rules for new data while preserving legacy rows

alter table public.courses
  add constraint courses_number_numeric_3_4_chk
  check (number ~ '^[0-9]{3,4}$') not valid;

alter table public.course_offerings
  add column if not exists term_id bigint references public.terms(id);

create unique index if not exists uq_course_offerings_course_term_id
  on public.course_offerings(course_id, term_id)
  where term_id is not null;
