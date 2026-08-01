-- autotrader / markets-pro schema
--
-- Every object is prefixed `mkt_` so it can live safely inside a shared
-- Supabase project without colliding with anything already in `public`.
--
-- SECURITY POSTURE: RLS is enabled on all tables with NO permissive policy.
-- That means anon and authenticated roles can read nothing by default; only the
-- service_role key (which bypasses RLS) can read or write. This is deliberate —
-- position and P&L data should not be world-readable just because a dashboard
-- wants to render it. To allow the browser to query directly, add an explicit
-- read policy (see the commented block at the bottom) and understand that doing
-- so publishes the data to anyone holding the anon key.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- Reference data
-- ---------------------------------------------------------------------------
create table if not exists mkt_instruments (
    key           text primary key,                 -- e.g. 'IN:RELIANCE'
    symbol        text        not null,
    region        text        not null,
    asset_class   text        not null default 'equity',
    currency      text        not null,
    tick_size     numeric(20, 8) not null,
    lot_size      numeric(20, 8) not null,
    multiplier    numeric(20, 8) not null default 1,
    name          text        not null default '',
    sector        text        not null default 'unknown',
    updated_at    timestamptz not null default now()
);

create index if not exists mkt_instruments_region_idx on mkt_instruments (region);

-- ---------------------------------------------------------------------------
-- Runs
-- ---------------------------------------------------------------------------
create table if not exists mkt_backtest_runs (
    id                     uuid primary key default gen_random_uuid(),
    label                  text        not null,
    created_at             timestamptz not null default now(),
    start_day              date        not null,
    end_day                date        not null,
    base_currency          text        not null,
    strategies             text[]      not null default '{}',
    regions                text[]      not null default '{}',
    starting_equity        numeric(24, 6),
    ending_equity          numeric(24, 6),
    total_return           numeric(18, 8),
    cagr                   numeric(18, 8),
    annual_volatility      numeric(18, 8),
    sharpe                 numeric(18, 8),
    sortino                numeric(18, 8),
    max_drawdown           numeric(18, 8),
    max_drawdown_days      integer,
    calmar                 numeric(18, 8),
    total_trades           integer     not null default 0,
    win_rate               numeric(18, 8),
    -- Nullable on purpose: profit factor is infinite when a run has no losing
    -- trades, and numeric cannot store infinity.
    profit_factor          numeric(18, 8),
    expectancy             numeric(24, 6),
    average_win            numeric(24, 6),
    average_loss           numeric(24, 6),
    max_consecutive_losses integer,
    total_costs            numeric(24, 6),
    total_fills            integer     not null default 0,
    rejections             integer     not null default 0,
    notes                  text        not null default '',
    constraint mkt_runs_period_valid check (end_day >= start_day)
);

create index if not exists mkt_runs_created_idx on mkt_backtest_runs (created_at desc);

-- ---------------------------------------------------------------------------
-- Equity curve
-- ---------------------------------------------------------------------------
create table if not exists mkt_equity_curve (
    id      bigserial primary key,
    run_id  uuid not null references mkt_backtest_runs (id) on delete cascade,
    day     date not null,
    equity  numeric(24, 6) not null,
    unique (run_id, day)
);

create index if not exists mkt_equity_run_day_idx on mkt_equity_curve (run_id, day);

-- ---------------------------------------------------------------------------
-- Completed round trips
-- ---------------------------------------------------------------------------
create table if not exists mkt_trades (
    id             bigserial primary key,
    run_id         uuid not null references mkt_backtest_runs (id) on delete cascade,
    instrument_key text not null,
    region         text not null,
    horizon        text not null,             -- 'long_term' | 'short_term'
    currency       text not null,
    entry_day      date not null,
    exit_day       date not null,
    entry_price    numeric(20, 8) not null,
    exit_price     numeric(20, 8) not null,
    quantity       numeric(20, 8) not null,
    gross_pnl      numeric(24, 6) not null,
    costs          numeric(24, 6) not null default 0,
    net_pnl        numeric(24, 6) not null,
    is_win         boolean not null,
    holding_days   integer not null default 0,
    return_pct     numeric(18, 8),
    exit_reason    text not null default '',
    constraint mkt_trades_dates_valid check (exit_day >= entry_day)
);

create index if not exists mkt_trades_run_idx    on mkt_trades (run_id);
create index if not exists mkt_trades_region_idx on mkt_trades (run_id, region);
create index if not exists mkt_trades_exit_idx   on mkt_trades (run_id, exit_day);

-- ---------------------------------------------------------------------------
-- Open positions at the end of a run
-- ---------------------------------------------------------------------------
create table if not exists mkt_positions (
    id             bigserial primary key,
    run_id         uuid not null references mkt_backtest_runs (id) on delete cascade,
    instrument_key text not null,
    symbol         text not null,
    region         text not null,
    currency       text not null,
    quantity       numeric(20, 8) not null,
    average_cost   numeric(20, 8) not null,
    last_price     numeric(20, 8) not null,
    market_value   numeric(24, 6) not null,
    unrealized_pnl numeric(24, 6) not null,
    realized_pnl   numeric(24, 6) not null default 0,
    weight         numeric(18, 8),
    opened_on      date,
    unique (run_id, instrument_key)
);

create index if not exists mkt_positions_run_idx on mkt_positions (run_id);

-- ---------------------------------------------------------------------------
-- Per-region attribution
-- ---------------------------------------------------------------------------
create table if not exists mkt_region_stats (
    id       bigserial primary key,
    run_id   uuid not null references mkt_backtest_runs (id) on delete cascade,
    region   text not null,
    trades   integer not null default 0,
    net_pnl  numeric(24, 6),
    win_rate numeric(18, 8),
    unique (run_id, region)
);

-- ---------------------------------------------------------------------------
-- Row level security: deny by default.
-- ---------------------------------------------------------------------------
alter table mkt_instruments    enable row level security;
alter table mkt_backtest_runs  enable row level security;
alter table mkt_equity_curve   enable row level security;
alter table mkt_trades         enable row level security;
alter table mkt_positions      enable row level security;
alter table mkt_region_stats   enable row level security;

-- To let the browser read these tables directly with the anon key, uncomment
-- the block below. Do this only if you accept that the data becomes readable by
-- anyone who has the anon key (which ships in client-side JavaScript).
--
-- create policy "public read" on mkt_backtest_runs for select to anon using (true);
-- create policy "public read" on mkt_equity_curve  for select to anon using (true);
-- create policy "public read" on mkt_trades        for select to anon using (true);
-- create policy "public read" on mkt_positions     for select to anon using (true);
-- create policy "public read" on mkt_region_stats  for select to anon using (true);
-- create policy "public read" on mkt_instruments   for select to anon using (true);
