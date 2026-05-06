-- Applied migration: add_crosslisted_course_id_index_for_performance
-- Purpose: satisfy performance index requirement on (course_id, crosslisted_course_id)

alter table public.course_crosslistings
  add column if not exists crosslisted_course_id bigint references public.courses(id);

update public.course_crosslistings cc
set crosslisted_course_id = c.id
from public.courses c
where c.subject = cc.cross_subject
  and c.number = cc.cross_number
  and (cc.crosslisted_course_id is null or cc.crosslisted_course_id <> c.id);

create index if not exists idx_course_crosslistings_course_id_crosslisted_course_id
  on public.course_crosslistings(course_id, crosslisted_course_id);
