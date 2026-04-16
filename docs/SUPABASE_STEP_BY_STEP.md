# Supabase Step-by-Step (Free Setup)

This guide is the easiest free path for thesis cloud sync.

## What I already prepared in code

- The receiver now supports Supabase writes directly.
- File: cloud_sync_server/app.py
- It still saves a local backup copy to cloud_sync_server/received_sync.jsonl.

## Step 1: Create Supabase project (click-by-click)

1. Open https://supabase.com and click Start your project.
2. Sign in with GitHub or email.
3. On the Dashboard, click New project.
4. If asked, create or select an Organization:
  - Click New organization.
  - Enter any organization name (example: SmartPOS Thesis).
  - Save.
5. In New project form, fill these fields:
  - Name: smartpos-thesis
  - Database Password: create and save this somewhere safe
  - Region: choose the nearest region to your location
6. Click Create new project.
7. Wait until status becomes healthy/ready (usually a few minutes).
8. Open the project dashboard page after it finishes provisioning.

## Step 2: Create table in Supabase SQL Editor

1. In the left sidebar, click SQL Editor.
2. Click New query.
3. Copy and paste the SQL below into the query area.
4. Click Run.
5. Confirm success message appears (no errors).

Run this SQL exactly:

create table if not exists public.smartpos_sync_events (
  id bigserial primary key,
  received_at timestamptz,
  queue_id bigint not null,
  entity_type text not null,
  sent_at text,
  payload jsonb not null,
  created_at timestamptz not null default now()
);

create unique index if not exists ux_smartpos_sync_events_queue_id
  on public.smartpos_sync_events(queue_id);

6. Optional quick check query (run after the create statements):

select table_name
from information_schema.tables
where table_schema = 'public'
  and table_name = 'smartpos_sync_events';

If you see one row, the table is ready.

## Step 3: Get your Supabase values

From Supabase Project Settings:

- SUPABASE_URL: your project URL (https://xxxxx.supabase.co)
- SUPABASE_SERVICE_ROLE_KEY: service_role key

Important: keep service role key private.

## Step 4: Start cloud receiver with Supabase env

In project root terminal:

export SMARTPOS_SERVER_API_KEY=thesis-demo-key
export SUPABASE_URL="https://YOUR_PROJECT.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="YOUR_SERVICE_ROLE_KEY"
export SUPABASE_TABLE="smartpos_sync_events"
export FAIL_ON_SUPABASE_ERROR=1
./scripts/start_cloud_receiver.sh

## Step 5: Start POS with sync enabled

In another terminal:

export SMARTPOS_CLOUD_SYNC_ENABLED=1
export SMARTPOS_CLOUD_SYNC_ENDPOINT="http://127.0.0.1:8080/sync"
export SMARTPOS_CLOUD_SYNC_API_KEY="thesis-demo-key"
./scripts/start_pos_with_local_cloud.sh

## Step 6: Test from app

1. Make a sale in POS.
2. Go to Owner > Reports.
3. Check Cloud Sync Status and click SYNC NOW.

## Step 7: Confirm data in Supabase

In Supabase SQL Editor run:

select id, queue_id, entity_type, created_at
from public.smartpos_sync_events
order by id desc
limit 20;

## Step 8: Enable owner-friendly cloud analytics views

You only do this once.

1. Open file: supabase/bootstrap_cloud.sql
2. Copy all SQL content.
3. In Supabase, open SQL Editor > New query.
4. Paste the SQL and click Run.
5. If no error appears, cloud report views are ready.

## Step 9: View cloud analytics with one command

From project root, run:

./scripts/view_supabase_reports.sh

This prints:

1. Top Products by Volume
2. Top Products by Frequency
3. Daily Sales Summary

This gives owner dashboard-like results from cloud data without manual SQL every time.

## Step 10: No-SQL view inside Supabase web (Table Editor)

If SQL Editor feels complex, use Table Editor with prebuilt views.

1. Run supabase/bootstrap_cloud.sql once (already includes all reporting views).
2. Open Supabase > Table Editor.
3. In the left list, open these owner views directly:
  - owner_history
  - owner_top_products_by_volume
  - owner_top_products_by_transactions
  - owner_daily_summary
  - owner_receipt_lines

For receipt details without SQL:

1. Open owner_receipt_lines.
2. Filter by Transaction ID.
3. Rows already show product, weight, and line total per receipt line.

## Why old transactions were missing in cloud

Only transactions that enter sync_queue are sent to cloud. Historical sales from before cloud-sync setup were not queued yet.

Fix implemented in app:

1. Owner > Reports > BACKFILL OLD SALES
2. This queues old local transactions into sync_queue
3. Then runs cloud sync so older transactions appear in cloud history/reports

## Defense-day safety plan

1. Primary demo: Supabase table updates live.
2. Backup demo: local file still captures records in cloud_sync_server/received_sync.jsonl.
3. If internet issues happen, continue local POS and show queued sync then retry.

## If sync fails

1. Check receiver health:
   http://127.0.0.1:8080/health
2. Ensure SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are correct.
3. Keep FAIL_ON_SUPABASE_ERROR=1 so failed writes return error and POS retries.
