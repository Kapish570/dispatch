-- Тестові дані (навчальні припущення). Відповідають прикладам openapi.yaml обох частин.
--   center     — 500 команд: приклад `normal`, багато успішних призначень підряд;
--   saltivka   — 3 команди: приклад `scarce` (x-capacity: 3) і дослід «10 заявок на 3 команди»;
--   test-race  — 3 команди: окремий район для дослідів конкуренції DPC (режим locked);
--   test-unprotected — 3 команди: окремий район для режиму без захисту (О1.4 DPC).
-- Паролі (для ЛР3): applicant1-pass, applicant2-pass, dispatcher-pass.

INSERT INTO district (id, name) VALUES
  ('center', 'Центральний'),
  ('saltivka', 'Салтівський'),
  ('test-race', 'Тестовий: конкуренція'),
  ('test-unprotected', 'Тестовий: без захисту');

INSERT INTO app_user (id, login, name, password_hash, role) VALUES
  ('u-applicant-1', 'applicant1', 'Олена Коваль',
   'pbkdf2_sha256$200000$Cf0ghgejdBsjO4fjsU+rzQ==$2vRR4luE7PbMrSc6L0KjDPAyTBkIFeLqLaz6ruYmdvs=', 'user'),
  ('u-applicant-2', 'applicant2', 'Петро Мельник',
   'pbkdf2_sha256$200000$Q+dzDtf6wLaOr/PTWGbPtg==$95rri1O33QMEc2whmtP6NK5zziusU5AoZmzZecJin0I=', 'user'),
  ('u-dispatcher', 'dispatcher', 'Диспетчер зміни',
   'pbkdf2_sha256$200000$/3/OZz0vUrBxEp40/46lcA==$TSyvlxO82QY2/iOQnVRLDrmwvQquIdwbXRaTqhunDMw=', 'staff');

INSERT INTO team (id, district_id, name, kits_available)
SELECT 'center-t' || lpad(n::text, 3, '0'), 'center', 'Центр-' || n, 20
  FROM generate_series(1, 500) AS n;

INSERT INTO team (id, district_id, name, kits_available)
SELECT d || '-t' || n, d, initcap(d) || '-' || n, 10
  FROM unnest(ARRAY['saltivka', 'test-race', 'test-unprotected']) AS d,
       generate_series(1, 3) AS n;

INSERT INTO district_teams (district_id, teams_total)
SELECT district_id, count(*) FROM team WHERE status <> 'off' GROUP BY district_id;
