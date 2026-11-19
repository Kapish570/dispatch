-- Web ЛР2 (О2.2): ключі ідемпотентності головної операції.
-- Рядок ключа вставляється в ТІЙ САМІЙ транзакції, що й предметна зміна: або фіксуються обидва
-- (ключ у стані completed зі збереженою відповіддю), або жоден.
CREATE TABLE idempotency_key (
  user_id          text NOT NULL REFERENCES app_user (id),
  operation        text NOT NULL,                       -- напр. 'POST /v1/requests'
  key              text NOT NULL CHECK (char_length(key) BETWEEN 8 AND 128),
  fingerprint      text NOT NULL,                       -- SHA-256 канонічного JSON тіла
  state            text NOT NULL CHECK (state IN ('processing', 'completed')),
  status_code      smallint,
  response_body    jsonb,
  response_headers jsonb,
  created_at       timestamptz NOT NULL DEFAULT now(),
  expires_at       timestamptz NOT NULL,
  PRIMARY KEY (user_id, operation, key),
  CHECK (state = 'processing' OR (status_code IS NOT NULL AND response_body IS NOT NULL))
);

-- прибирання прострочених ключів порціями
CREATE INDEX idempotency_key_expires ON idempotency_key (expires_at);
