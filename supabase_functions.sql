-- Backend logic for the STATIC (GitHub Pages) version of the tracer.
--
-- Run this in Supabase AFTER supabase_schema.sql. It replaces the Flask
-- backend: the browser calls these functions directly with the PUBLIC anon key,
-- and all token checks happen inside the database.
--
-- Security model:
--   * The base tables have RLS enabled with no public policies, and below we
--     REVOKE all direct table access from anon/authenticated. So the anon key
--     cannot read or write the tables directly.
--   * These functions are SECURITY DEFINER (they run as their owner, which
--     bypasses RLS) and validate share_token / owner_key / member_token
--     themselves before doing anything. Only these functions are exposed.
--   * The service_role key is NEVER used by the static site.

-- Lock the tables so the anon key can only go through the functions below.
revoke all on public.sessions  from anon, authenticated;
revoke all on public.members   from anon, authenticated;
revoke all on public.locations from anon, authenticated;

-- ---------------------------------------------------------------------------
-- create_session: make a new tracking link.
-- ---------------------------------------------------------------------------
create or replace function public.create_session(
    p_label          text,
    p_expiry_minutes int default 1440,
    p_max_members    int default 5
) returns json
language plpgsql
security definer
set search_path = public
as $$
declare
    v_label   text := left(coalesce(nullif(trim(p_label), ''), ''), 200);
    v_minutes int  := greatest(5, least(10080, coalesce(p_expiry_minutes, 1440)));
    v_max     int  := greatest(1, least(10, coalesce(p_max_members, 5)));
    v_share   text := replace(gen_random_uuid()::text, '-', '');
    v_owner   text := replace(gen_random_uuid()::text, '-', '')
                      || replace(gen_random_uuid()::text, '-', '');
    v_expires timestamptz := now() + make_interval(mins => v_minutes);
begin
    if v_label = '' then
        return json_build_object('error', 'A label describing the request is required.');
    end if;

    insert into public.sessions
        (share_token, owner_key, label, created_at, expires_at, max_members, active)
    values (v_share, v_owner, v_label, now(), v_expires, v_max, true);

    return json_build_object(
        'share_token', v_share,
        'owner_key',   v_owner,
        'expires_at',  v_expires,
        'max_members', v_max
    );
end;
$$;

-- ---------------------------------------------------------------------------
-- session_info: public info a share page needs before joining (no owner_key).
-- ---------------------------------------------------------------------------
create or replace function public.session_info(
    p_share_token text
) returns json
language plpgsql
security definer
set search_path = public
as $$
declare
    v_session public.sessions%rowtype;
    v_count   int;
begin
    select * into v_session from public.sessions where share_token = p_share_token;
    if not found then
        return json_build_object('error', 'not_found');
    end if;
    select count(*) into v_count from public.members where session_id = v_session.id;
    return json_build_object(
        'label',        v_session.label,
        'active',       v_session.active and (v_session.expires_at is null or now() < v_session.expires_at),
        'expired',      (v_session.expires_at is not null and now() >= v_session.expires_at),
        'member_count', v_count,
        'max_members',  v_session.max_members,
        'full',         v_count >= v_session.max_members
    );
end;
$$;

-- ---------------------------------------------------------------------------
-- join_session: a device joins as a member (idempotent; enforces the cap).
-- ---------------------------------------------------------------------------
create or replace function public.join_session(
    p_share_token  text,
    p_name         text default null,
    p_member_token text default null
) returns json
language plpgsql
security definer
set search_path = public
as $$
declare
    v_session public.sessions%rowtype;
    v_member  public.members%rowtype;
    v_count   int;
    v_name    text := left(coalesce(nullif(trim(p_name), ''), 'Guest'), 40);
    v_token   text;
begin
    select * into v_session from public.sessions where share_token = p_share_token;
    if not found then
        return json_build_object('error', 'not_found');
    end if;
    if not v_session.active
       or (v_session.expires_at is not null and now() >= v_session.expires_at) then
        return json_build_object('error', 'This tracking session has ended or expired.');
    end if;

    -- Returning member: reuse the existing membership.
    if p_member_token is not null then
        select * into v_member from public.members
            where session_id = v_session.id and member_token = p_member_token;
        if found then
            select count(*) into v_count from public.members where session_id = v_session.id;
            return json_build_object(
                'member_token', v_member.member_token,
                'member_id',    v_member.id,
                'name',         v_member.name,
                'max_members',  v_session.max_members,
                'member_count', v_count
            );
        end if;
    end if;

    -- New member: enforce the cap.
    select count(*) into v_count from public.members where session_id = v_session.id;
    if v_count >= v_session.max_members then
        return json_build_object(
            'error',
            format('This link is full (%s people have already joined).', v_session.max_members)
        );
    end if;

    v_token := replace(gen_random_uuid()::text, '-', '');
    insert into public.members (session_id, member_token, name, joined_at)
    values (v_session.id, v_token, v_name, now())
    returning * into v_member;

    return json_build_object(
        'member_token', v_token,
        'member_id',    v_member.id,
        'name',         v_name,
        'max_members',  v_session.max_members,
        'member_count', v_count + 1
    );
end;
$$;

-- ---------------------------------------------------------------------------
-- ping: a member posts a location fix.
-- ---------------------------------------------------------------------------
create or replace function public.ping(
    p_share_token  text,
    p_member_token text,
    p_lat          double precision,
    p_lng          double precision,
    p_accuracy     double precision default null,
    p_client_ts    text default null
) returns json
language plpgsql
security definer
set search_path = public
as $$
declare
    v_session public.sessions%rowtype;
    v_member  public.members%rowtype;
begin
    select * into v_session from public.sessions where share_token = p_share_token;
    if not found then
        return json_build_object('error', 'not_found');
    end if;
    if not v_session.active
       or (v_session.expires_at is not null and now() >= v_session.expires_at) then
        return json_build_object('error', 'ended');
    end if;

    select * into v_member from public.members
        where session_id = v_session.id and member_token = p_member_token;
    if not found then
        return json_build_object('error', 'forbidden');
    end if;

    if p_lat is null or p_lng is null
       or p_lat < -90 or p_lat > 90 or p_lng < -180 or p_lng > 180 then
        return json_build_object('error', 'bad_coords');
    end if;

    insert into public.locations
        (session_id, member_id, lat, lng, accuracy, client_ts, server_ts)
    values (v_session.id, v_member.id, p_lat, p_lng, p_accuracy,
            left(coalesce(p_client_ts, ''), 64), now());

    update public.members set last_seen = now() where id = v_member.id;
    return json_build_object('ok', true);
end;
$$;

-- ---------------------------------------------------------------------------
-- get_locations: owner-only. Returns each member with latest fix + trail.
-- ---------------------------------------------------------------------------
create or replace function public.get_locations(
    p_share_token text,
    p_owner_key   text
) returns json
language plpgsql
security definer
set search_path = public
as $$
declare
    v_session public.sessions%rowtype;
    v_members json;
begin
    select * into v_session from public.sessions where share_token = p_share_token;
    if not found then
        return json_build_object('error', 'not_found');
    end if;
    if v_session.owner_key is distinct from p_owner_key then
        return json_build_object('error', 'forbidden');
    end if;

    select coalesce(json_agg(row_to_json(m) order by m.id), '[]'::json) into v_members
    from (
        select
            mem.id,
            mem.name,
            mem.joined_at,
            mem.last_seen,
            (select row_to_json(l) from (
                select loc.lat, loc.lng, loc.accuracy, loc.server_ts
                from public.locations loc
                where loc.member_id = mem.id
                order by loc.id desc
                limit 1
            ) l) as latest,
            (select coalesce(json_agg(json_build_array(t.lat, t.lng) order by t.id), '[]'::json)
             from (
                select loc.id, loc.lat, loc.lng
                from public.locations loc
                where loc.member_id = mem.id
                order by loc.id desc
                limit 60
             ) t) as trail
        from public.members mem
        where mem.session_id = v_session.id
    ) m;

    return json_build_object(
        'active',       v_session.active and (v_session.expires_at is null or now() < v_session.expires_at),
        'expired',      (v_session.expires_at is not null and now() >= v_session.expires_at),
        'expires_at',   v_session.expires_at,
        'label',        v_session.label,
        'max_members',  v_session.max_members,
        'member_count', (select count(*) from public.members where session_id = v_session.id),
        'members',      v_members
    );
end;
$$;

-- Expose only these functions to the public anon (and logged-in) roles.
grant execute on function public.create_session(text, int, int)                       to anon, authenticated;
grant execute on function public.session_info(text)                                    to anon, authenticated;
grant execute on function public.join_session(text, text, text)                        to anon, authenticated;
grant execute on function public.ping(text, text, double precision, double precision, double precision, text) to anon, authenticated;
grant execute on function public.get_locations(text, text)                             to anon, authenticated;
