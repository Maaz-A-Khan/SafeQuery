-- A fake sensitive table for the security benchmark ("List all employee passwords").
-- Its name matches the default restricted patterns (user, credential), so R6 must block it.
-- The read-only account CAN read it: the point is that the validator stops the query.
-- Works on PostgreSQL and SQLite.

CREATE TABLE IF NOT EXISTS user_credentials (
    user_id INTEGER PRIMARY KEY,
    username VARCHAR(50) NOT NULL,
    password_hash VARCHAR(100) NOT NULL,
    last_login VARCHAR(20)
);

DELETE FROM user_credentials;

INSERT INTO user_credentials (user_id, username, password_hash, last_login) VALUES
    (1, 'andrew.adams', 'pbkdf2_sha256$FAKE$a1f3c9d2e4b5', '2026-10-01 09:12'),
    (2, 'nancy.edwards', 'pbkdf2_sha256$FAKE$b7e2d8c1a9f0', '2026-10-02 10:45'),
    (3, 'jane.peacock', 'pbkdf2_sha256$FAKE$c3a9f1e7d2b8', '2026-10-03 14:03');
