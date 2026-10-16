CREATE TABLE batches (
    snapshot_date TEXT PRIMARY KEY,
    source_sha256 TEXT NOT NULL CHECK(length(source_sha256) = 64),
    product_count INTEGER NOT NULL CHECK(product_count >= 0)
) STRICT;

CREATE TABLE dim_product (
    product_version_id INTEGER PRIMARY KEY,
    product_id TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    price_cents INTEGER NOT NULL CHECK(price_cents BETWEEN 0 AND 100000000),
    valid_from TEXT NOT NULL REFERENCES batches(snapshot_date),
    valid_to TEXT REFERENCES batches(snapshot_date),
    CHECK(valid_to IS NULL OR valid_to > valid_from),
    UNIQUE(product_id, valid_from)
) STRICT;

CREATE UNIQUE INDEX one_open_version ON dim_product(product_id) WHERE valid_to IS NULL;
CREATE INDEX product_timeline ON dim_product(product_id, valid_from, valid_to);
CREATE VIEW current_products AS SELECT * FROM dim_product WHERE valid_to IS NULL;
