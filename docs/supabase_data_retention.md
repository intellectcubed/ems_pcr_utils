# Supabase Data Retention

The application does not automatically delete records from the `rip_and_runs` table. Without intervention, parsed incident data accumulates indefinitely.

## pg_cron (Recommended)

Supabase supports `pg_cron`, a PostgreSQL extension for scheduling SQL jobs inside the database. No additional infrastructure is required.

### Setup

1. In the Supabase dashboard go to **Database → Extensions** and enable **pg_cron**.

2. Open the **SQL Editor** and run:

```sql
SELECT cron.schedule(
  'cleanup-old-incidents',
  '0 2 * * *',           -- nightly at 2am
  $$
    DELETE FROM rip_and_runs
    WHERE incident_date < NOW() - INTERVAL '90 days'
  $$
);
```

Adjust `90 days` to the desired retention window.

If PDFs are stored in Supabase Storage, delete the corresponding objects in the same job:

```sql
SELECT cron.schedule(
  'cleanup-old-incidents',
  '0 2 * * *',
  $$
    -- Delete storage objects for expired incidents
    DELETE FROM storage.objects
    WHERE bucket_id = 'pcr-pdfs'
    AND name IN (
      SELECT incident_number::text || '.pdf'
      FROM rip_and_runs
      WHERE incident_date < NOW() - INTERVAL '90 days'
    );

    -- Delete the database rows
    DELETE FROM rip_and_runs
    WHERE incident_date < NOW() - INTERVAL '90 days';
  $$
);
```

### Managing the Job

```sql
-- View scheduled jobs
SELECT * FROM cron.job;

-- View recent execution history
SELECT * FROM cron.job_run_details ORDER BY start_time DESC LIMIT 20;

-- Remove the job
SELECT cron.unschedule('cleanup-old-incidents');
```

### Cron Schedule Reference

| Schedule | Expression |
|---|---|
| Nightly at 2am | `0 2 * * *` |
| Weekly Sunday midnight | `0 0 * * 0` |
| Monthly 1st at 3am | `0 3 1 * *` |
