-- Link certificates to majors based on course overlap heuristics
-- Run once to create the table
CREATE TABLE IF NOT EXISTS public.program_major_links (
  certificate_program_id bigint PRIMARY KEY,
  major_program_id bigint,
  overlap_count integer NOT NULL DEFAULT 0,
  cert_course_count integer NOT NULL DEFAULT 0,
  overlap_ratio numeric NOT NULL DEFAULT 0,
  method text NOT NULL DEFAULT 'OVERLAP_RATIO',
  tied boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT program_major_links_certificate_fkey
    FOREIGN KEY (certificate_program_id) REFERENCES public.programs(id) ON DELETE CASCADE,
  CONSTRAINT program_major_links_major_fkey
    FOREIGN KEY (major_program_id) REFERENCES public.programs(id) ON DELETE SET NULL
);
