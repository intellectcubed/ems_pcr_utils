alter table public.rip_and_runs enable row level security;

-- Allow authenticated users to read all rows
create policy "Authenticated users can read" 
on public.rip_and_runs
for select
to authenticated
using (true);

-- Allow authenticated users to insert
create policy "Authenticated users can insert" 
on public.rip_and_runs
for insert
to authenticated
with check (true);
