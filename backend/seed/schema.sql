-- PropCloser tables. Safe to run repeatedly (the API runs it on every startup).
-- LangGraph creates its own checkpoint/store tables via .setup().

create table if not exists listings (
  id            int primary key,
  title         text   not null,
  area          text   not null,
  sector        text,
  property_type text   not null,              -- house | flat | plot
  purpose       text   not null,              -- sale | rent
  beds          int    not null default 0,
  baths         int    not null default 0,
  size_marla    numeric,
  price_pkr     bigint not null,              -- full rupees; monthly rent when purpose = rent
  description   text
);

create table if not exists leads (
  user_id       text primary key,
  name          text,
  status        text not null default 'new',  -- new | qualified | visit_booked
  budget_pkr    bigint,
  area          text,
  purpose       text,
  property_type text,
  beds          int,
  timeline      text,
  financing     text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create table if not exists visits (
  id          serial primary key,
  user_id     text not null,
  listing_id  int  not null references listings(id),
  slot_time   timestamptz not null,
  status      text not null default 'pending',  -- pending | confirmed | cancelled
  created_at  timestamptz not null default now()
);

-- capacity per slot is enforced in repo.confirm_visit (advisory lock + count)
drop index if exists visits_one_confirmed_per_slot;
create index if not exists visits_slot_idx on visits (listing_id, slot_time) where status = 'confirmed';
create index if not exists visits_user_idx on visits (user_id);

create table if not exists followups (
  id          serial primary key,
  user_id     text not null,
  message     text not null,
  due_at      timestamptz,
  status      text not null default 'pending_approval',  -- pending_approval | approved | rejected
  created_at  timestamptz not null default now()
);
create index if not exists followups_user_idx on followups (user_id);

-- model spend per day (app/budget.py), so the cap survives restarts
create table if not exists spend (
  day  date primary key,
  usd  double precision not null default 0
);
