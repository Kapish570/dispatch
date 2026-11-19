-- Частина DPC: запити гарячої лінії, що проходять обмежену чергу й пул обробників.
-- request_id — спільний ідентифікатор (розділ 6 картки): для прийнятого запиту той самий id
-- отримує заявка help_request (channel = 'hotline').

CREATE TABLE assignment_request (
  id              text PRIMARY KEY,
  district_id     text NOT NULL,
  kind            text NOT NULL CHECK (kind IN ('medicine', 'escort', 'food', 'other')),
  address         text NOT NULL DEFAULT 'дзвінок на гарячу лінію',
  state           text NOT NULL CHECK (state IN ('queued', 'processing', 'done', 'rejected', 'failed')),
  reason          text,
  team_id         text,
  help_request_id text REFERENCES help_request (id),
  mode            text NOT NULL DEFAULT 'locked' CHECK (mode IN ('locked', 'unprotected')),
  arrived_at      timestamptz NOT NULL DEFAULT now(),
  finished_at     timestamptz
);

CREATE INDEX assignment_request_state ON assignment_request (state);
CREATE INDEX assignment_request_district ON assignment_request (district_id);
