-- Run this once in your Supabase project: SQL Editor → New query → paste → Run.
-- Creates the tables the location tracer needs.
--
-- Access model: the Flask backend talks to these tables with the SERVICE_ROLE
-- key, which bypasses Row-Level Security. The browser never touches Supabase
-- directly, so RLS is enabled with no public policies (deny-by-default) — the
-- anon key cannot read or write these tables. All consent/auth is enforced by
-- the Flask app (owner_key for viewing, browser permission for sharing).

create table if not exists public.sessions (
    id          bigint generated always as identity primary key,
    share_token text        not null unique,
    owner_key   text        not null,
    label       text        not null,
    created_at  timestamptz not null default now(),
    expires_at  timestamptz,
    max_members integer     not null default 5,
    active      boolean     not null default true
);

-- Each device that joins a link becomes a member (up to max_members).
create table if not exists public.members (
    id           bigint generated always as identity primary key,
    session_id   bigint      not null references public.sessions (id) on delete cascade,
    member_token text        not null unique,
    name         text        not null,
    joined_at    timestamptz not null default now(),
    last_seen    timestamptz
);

create table if not exists public.locations (
    id         bigint generated always as identity primary key,
    session_id bigint      not null references public.sessions (id) on delete cascade,
    member_id  bigint      references public.members (id) on delete cascade,
    lat        double precision not null,
    lng        double precision not null,
    accuracy   double precision,
    client_ts  text,
    server_ts  timestamptz not null default now()
);

create index if not exists idx_locations_session
    on public.locations (session_id, id);
create index if not exists idx_members_session
    on public.members (session_id);

-- Lock the tables down. Service role bypasses RLS; anon/public get nothing.
alter table public.sessions  enable row level security;
alter table public.members   enable row level security;
alter table public.locations enable row level security;
