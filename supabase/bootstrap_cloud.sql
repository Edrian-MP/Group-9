-- SmartPOS Cloud Bootstrap (single owner view set)
-- Run once in Supabase SQL Editor.

-- 0) Cleanup legacy views ----------------------------------------------------
drop view if exists public.owner_receipt_lines_readable;
drop view if exists public.owner_daily_summary_readable;
drop view if exists public.owner_top_products_by_transactions_readable;
drop view if exists public.owner_top_products_by_volume_readable;
drop view if exists public.owner_history_readable;
drop view if exists public.owner_receipt_lines_api;
drop view if exists public.owner_receipts_with_items_api;
drop view if exists public.owner_history_api;
drop view if exists public.owner_daily_summary_api;
drop view if exists public.owner_top_products_by_transactions_api;
drop view if exists public.owner_top_products_by_volume_api;
drop view if exists public.owner_sales_items_api;

drop view if exists public.smartpos_receipts_with_items;
drop view if exists public.smartpos_history_grouped;
drop view if exists public.smartpos_daily_sales_summary;
drop view if exists public.smartpos_top_products_frequency;
drop view if exists public.smartpos_top_products_volume;
drop view if exists public.smartpos_sales_items_expanded;

drop view if exists public.owner_receipt_lines;
drop view if exists public.owner_daily_summary;
drop view if exists public.owner_top_products_by_transactions;
drop view if exists public.owner_top_products_by_volume;
drop view if exists public.owner_history;

-- 1) Base table ---------------------------------------------------------------
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

-- 2) Owner history view ------------------------------------------------------
create or replace view public.owner_history as
with owner_sales_items as (
  with ranked_events as (
    select
      e.*,
      nullif(e.payload->>'transaction_id', '') as tx_id,
      row_number() over (
        partition by nullif(e.payload->>'transaction_id', '')
        order by e.created_at desc, e.id desc
      ) as rn
    from public.smartpos_sync_events e
    where coalesce(e.entity_type, '') = 'sales_transaction'
      and nullif(e.payload->>'transaction_id', '') is not null
  )
  select
    r.tx_id as transaction_id,
    nullif(r.payload->>'payment_method', '') as payment_method,
    nullif(r.payload->'seller'->>'name', '') as seller_name,
    nullif(r.payload->>'timestamp', '')::timestamp as sale_timestamp,
    item.product_name,
    item.weight,
    item.total_price
  from ranked_events r
  cross join lateral jsonb_to_recordset(coalesce(r.payload->'items', '[]'::jsonb))
    as item(product_name text, weight numeric, total_price numeric)
  where r.rn = 1
)
select
  min(sale_timestamp) as sale_time,
  transaction_id,
  count(*) as item_count,
  round(sum(total_price)::numeric, 2) as total_amount_php,
  max(coalesce(seller_name, 'Unknown')) as seller_name,
  max(coalesce(payment_method, 'Unknown')) as payment_method
from owner_sales_items
group by transaction_id
order by min(sale_timestamp) desc;

-- 3) Owner top products by volume -------------------------------------------
create or replace view public.owner_top_products_by_volume as
with owner_sales_items as (
  with ranked_events as (
    select
      e.*,
      nullif(e.payload->>'transaction_id', '') as tx_id,
      row_number() over (
        partition by nullif(e.payload->>'transaction_id', '')
        order by e.created_at desc, e.id desc
      ) as rn
    from public.smartpos_sync_events e
    where coalesce(e.entity_type, '') = 'sales_transaction'
      and nullif(e.payload->>'transaction_id', '') is not null
  )
  select
    r.tx_id as transaction_id,
    item.product_name,
    item.weight,
    item.total_price
  from ranked_events r
  cross join lateral jsonb_to_recordset(coalesce(r.payload->'items', '[]'::jsonb))
    as item(product_name text, weight numeric, total_price numeric)
  where r.rn = 1
)
select
  product_name,
  round(sum(weight)::numeric, 3) as total_kg_sold,
  count(distinct transaction_id) as transactions,
  round(sum(total_price)::numeric, 2) as revenue_php
from owner_sales_items
group by product_name
order by total_kg_sold desc;

-- 4) Owner top products by transactions -------------------------------------
create or replace view public.owner_top_products_by_transactions as
with owner_sales_items as (
  with ranked_events as (
    select
      e.*,
      nullif(e.payload->>'transaction_id', '') as tx_id,
      row_number() over (
        partition by nullif(e.payload->>'transaction_id', '')
        order by e.created_at desc, e.id desc
      ) as rn
    from public.smartpos_sync_events e
    where coalesce(e.entity_type, '') = 'sales_transaction'
      and nullif(e.payload->>'transaction_id', '') is not null
  )
  select
    r.tx_id as transaction_id,
    item.product_name,
    item.weight,
    item.total_price
  from ranked_events r
  cross join lateral jsonb_to_recordset(coalesce(r.payload->'items', '[]'::jsonb))
    as item(product_name text, weight numeric, total_price numeric)
  where r.rn = 1
)
select
  product_name,
  count(distinct transaction_id) as transactions,
  count(*) as line_items,
  round(sum(weight)::numeric, 3) as total_kg_sold,
  round(sum(total_price)::numeric, 2) as revenue_php
from owner_sales_items
group by product_name
order by transactions desc, line_items desc;

-- 5) Owner daily summary -----------------------------------------------------
create or replace view public.owner_daily_summary as
with owner_sales_items as (
  with ranked_events as (
    select
      e.*,
      nullif(e.payload->>'transaction_id', '') as tx_id,
      row_number() over (
        partition by nullif(e.payload->>'transaction_id', '')
        order by e.created_at desc, e.id desc
      ) as rn
    from public.smartpos_sync_events e
    where coalesce(e.entity_type, '') = 'sales_transaction'
      and nullif(e.payload->>'transaction_id', '') is not null
  )
  select
    r.tx_id as transaction_id,
    nullif(r.payload->>'timestamp', '')::timestamp as sale_timestamp,
    item.weight,
    item.total_price
  from ranked_events r
  cross join lateral jsonb_to_recordset(coalesce(r.payload->'items', '[]'::jsonb))
    as item(product_name text, weight numeric, total_price numeric)
  where r.rn = 1
)
select
  date(sale_timestamp) as sale_date,
  count(distinct transaction_id) as transaction_count,
  round(sum(total_price)::numeric, 2) as total_revenue_php,
  round(sum(weight)::numeric, 3) as total_kg_sold
from owner_sales_items
group by date(sale_timestamp)
order by sale_date desc;

-- 6) Owner receipt lines -----------------------------------------------------
create or replace view public.owner_receipt_lines as
with owner_sales_items as (
  with ranked_events as (
    select
      e.*,
      nullif(e.payload->>'transaction_id', '') as tx_id,
      row_number() over (
        partition by nullif(e.payload->>'transaction_id', '')
        order by e.created_at desc, e.id desc
      ) as rn
    from public.smartpos_sync_events e
    where coalesce(e.entity_type, '') = 'sales_transaction'
      and nullif(e.payload->>'transaction_id', '') is not null
  )
  select
    r.tx_id as transaction_id,
    nullif(r.payload->>'timestamp', '')::timestamp as sale_time,
    nullif(r.payload->'seller'->>'name', '') as seller_name,
    nullif(r.payload->>'payment_method', '') as payment_method,
    item.product_name,
    item.weight,
    item.total_price
  from ranked_events r
  cross join lateral jsonb_to_recordset(coalesce(r.payload->'items', '[]'::jsonb))
    as item(product_name text, weight numeric, total_price numeric)
  where r.rn = 1
)
select
  sale_time,
  transaction_id,
  coalesce(seller_name, 'Unknown') as seller_name,
  coalesce(payment_method, 'Unknown') as payment_method,
  product_name,
  weight,
  total_price
from owner_sales_items
order by sale_time desc, transaction_id, product_name;
