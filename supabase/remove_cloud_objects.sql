-- WARNING: This removes SmartPOS cloud reporting views and data table.
-- Run in Supabase SQL Editor only if you want a full clean slate.

-- Drop owner views (single naming) and legacy api/readable variants
drop view if exists public.owner_receipt_lines;
drop view if exists public.owner_daily_summary;
drop view if exists public.owner_top_products_by_transactions;
drop view if exists public.owner_top_products_by_volume;
drop view if exists public.owner_history;
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

-- Drop technical/reporting views
drop view if exists public.smartpos_receipts_with_items;
drop view if exists public.smartpos_history_grouped;
drop view if exists public.smartpos_daily_sales_summary;
drop view if exists public.smartpos_top_products_frequency;
drop view if exists public.smartpos_top_products_volume;
drop view if exists public.smartpos_sales_items_expanded;

-- Drop base cloud table
drop table if exists public.smartpos_sync_events;
