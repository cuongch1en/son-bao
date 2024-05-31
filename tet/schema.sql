CREATE TABLE targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    last_content TEXT,
    valid_domain TEXT
);
