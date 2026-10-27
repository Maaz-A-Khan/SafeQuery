"""A small SQLite database for the connection and schema tests."""

import sqlite3

import pytest

SHOP = """
CREATE TABLE artist (artist_id INTEGER PRIMARY KEY, name VARCHAR(120));
CREATE TABLE album (
    album_id INTEGER PRIMARY KEY,
    title VARCHAR(160) NOT NULL,
    artist_id INTEGER NOT NULL REFERENCES artist(artist_id)
);
CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    status VARCHAR(20) NOT NULL,
    note TEXT,
    api_token VARCHAR(40)
);
CREATE TABLE user_credentials (user_id INTEGER PRIMARY KEY, username VARCHAR(50), password_hash VARCHAR(100));
CREATE TABLE authors (author_id INTEGER PRIMARY KEY, name VARCHAR(50));
CREATE VIEW album_titles AS SELECT title FROM album;

INSERT INTO artist VALUES (1, 'AC/DC'), (2, 'Accept');
INSERT INTO album VALUES (1, 'For Those About To Rock', 1), (2, 'Balls to the Wall', 2);
INSERT INTO orders VALUES
    (1, 'shipped', 'call first', 'tok1'), (2, 'shipped', 'leave at door', 'tok2'),
    (3, 'pending', NULL, 'tok3'), (4, 'cancelled', NULL, 'tok4'), (5, 'pending', NULL, 'tok5');
INSERT INTO user_credentials VALUES (1, 'admin', 'admin'), (2, 'admin2', 'admin');
INSERT INTO authors VALUES (1, 'Austen');
"""


@pytest.fixture
def shop_db(tmp_path):
    path = tmp_path / "shop db.sqlite"   # the space checks the file-URI rewrite
    with sqlite3.connect(path) as conn:
        conn.executescript(SHOP)
    conn.close()
    return path


@pytest.fixture
def shop_url(shop_db):
    return f"sqlite:///{shop_db.as_posix()}"
