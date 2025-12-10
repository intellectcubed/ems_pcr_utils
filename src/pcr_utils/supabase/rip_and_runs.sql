create table public.rip_and_runs (
  incident_number   bigint        not null,
  unit_id           text          not null,
  created_date      timestamptz   not null default now(),
  content           text          not null,

  incident_date     timestamptz not null,
  location          varchar(300),
  incident_type     varchar(20),

  -- Composite primary key
  constraint rip_and_runs_pkey primary key (incident_number, unit_id)
);
