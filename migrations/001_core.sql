-- C30 «Диспетчерська допомоги»: спільна схема Web + DPC (одна база PostgreSQL).
-- Головний інваріант: команда виконує одну заявку.
--   * у БД його захищає частковий унікальний індекс help_request_one_active_per_team;
--   * правило призначення (вільна команда району) виконує одна функція assign_team(),
--     яку викликають і Web (сайт), і DPC (гаряча лінія) — однакове правило, атомарно в базі.

CREATE TABLE district (
  id   text PRIMARY KEY,
  name text NOT NULL,
  tz   text NOT NULL DEFAULT 'Europe/Kyiv'       -- назва зони окремо: timestamptz зберігає момент
);

CREATE TABLE app_user (
  id            text PRIMARY KEY,
  login         text NOT NULL UNIQUE,
  name          text NOT NULL,
  password_hash text NOT NULL,                    -- для ЛР3; до ЛР3 користувача задає X-User-Id
  role          text NOT NULL CHECK (role IN ('user', 'staff'))
);

-- Волонтерська команда району. kits_available — набори допомоги на складі команди (цілі).
CREATE TABLE team (
  id             text PRIMARY KEY,
  district_id    text NOT NULL REFERENCES district (id),
  name           text NOT NULL,
  status         text NOT NULL DEFAULT 'free' CHECK (status IN ('free', 'busy', 'off')),
  kits_available integer NOT NULL DEFAULT 0 CHECK (kits_available >= 0),
  version        bigint NOT NULL DEFAULT 1 CHECK (version > 0)
);
CREATE INDEX team_district_status ON team (district_id, status);

-- Ресурс DPC (картка DPC, розділ 2): скільки команд району на чергуванні й скільки зайнято.
-- CHECK (busy <= teams_total) навмисно немає: дослід О1.4 DPC без синхронізації має
-- показати порушення (на окремому тестовому районі). У захищеному режимі межу
-- перевіряє assign_team() під блокуванням рядка.
CREATE TABLE district_teams (
  district_id text PRIMARY KEY REFERENCES district (id),
  teams_total integer NOT NULL CHECK (teams_total >= 0),
  busy        integer NOT NULL DEFAULT 0 CHECK (busy >= 0)
);

-- Заявка на допомогу. Канал web — сайт/застосунок (частина Web), hotline — гаряча лінія (черга DPC).
CREATE TABLE help_request (
  id              text PRIMARY KEY,
  user_id         text REFERENCES app_user (id),
  channel         text NOT NULL CHECK (channel IN ('web', 'hotline')),
  district_id     text NOT NULL REFERENCES district (id),
  address         text NOT NULL CHECK (char_length(address) BETWEEN 3 AND 300),
  kind            text NOT NULL CHECK (kind IN ('medicine', 'escort', 'food', 'other')),
  priority        smallint NOT NULL DEFAULT 2 CHECK (priority BETWEEN 1 AND 3),
  kits            integer NOT NULL DEFAULT 0 CHECK (kits BETWEEN 0 AND 20),
  team_id         text REFERENCES team (id),
  status          text NOT NULL CHECK (status IN ('new', 'assigned', 'on_way', 'done', 'cancelled')),
  version         bigint NOT NULL DEFAULT 1 CHECK (version > 0),
  created_at      timestamptz NOT NULL DEFAULT now(),
  accept_deadline timestamptz,
  CHECK (channel = 'hotline' OR user_id IS NOT NULL),
  CHECK (status NOT IN ('assigned', 'on_way') OR team_id IS NOT NULL)
);

-- ІНВАРІАНТ: одна команда — не більше однієї активної заявки.
CREATE UNIQUE INDEX help_request_one_active_per_team
  ON help_request (team_id) WHERE status IN ('assigned', 'on_way');

-- Список «мої заявки» від найновіших: порядок (created_at, id).
CREATE INDEX help_request_user_created ON help_request (user_id, created_at DESC, id DESC);

-- Єдине предметне правило призначення для обох каналів.
-- Блокування рядка district_teams серіалізує призначення в районі; перевірка «є вільна команда»
-- і зміна ресурсу виконуються в одній транзакції того, хто викликає функцію.
CREATE FUNCTION assign_team(p_district text, p_kits integer) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
  v_total integer;
  v_busy  integer;
  v_team  text;
BEGIN
  SELECT teams_total, busy INTO v_total, v_busy
    FROM district_teams WHERE district_id = p_district FOR UPDATE;
  IF NOT FOUND OR v_busy >= v_total THEN
    RETURN NULL;
  END IF;

  SELECT id INTO v_team
    FROM team
   WHERE district_id = p_district AND status = 'free' AND kits_available >= p_kits
   ORDER BY id
   LIMIT 1
   FOR UPDATE;
  IF v_team IS NULL THEN
    RETURN NULL;
  END IF;

  UPDATE team
     SET status = 'busy', kits_available = kits_available - p_kits, version = version + 1
   WHERE id = v_team;
  UPDATE district_teams SET busy = busy + 1 WHERE district_id = p_district;
  RETURN v_team;
END;
$$;
