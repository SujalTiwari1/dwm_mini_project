-- MedStock data warehouse: star schema (PostgreSQL)
-- Idempotent: safe to run repeatedly (CREATE ... IF NOT EXISTS). The ETL truncates and reloads data.

CREATE SCHEMA IF NOT EXISTS warehouse;

-- ===========================================================================
-- DIMENSIONS
-- ===========================================================================

-- Grain: one calendar day. Surrogate key is the smart key YYYYMMDD.
CREATE TABLE IF NOT EXISTS warehouse.dim_date (
    date_key     INTEGER     PRIMARY KEY CHECK (date_key BETWEEN 19000101 AND 29991231),
    full_date    DATE        NOT NULL UNIQUE,
    day          SMALLINT    NOT NULL CHECK (day BETWEEN 1 AND 31),
    day_of_week  SMALLINT    NOT NULL CHECK (day_of_week BETWEEN 1 AND 7),   -- ISO: 1 = Monday
    day_name     VARCHAR(9)  NOT NULL,
    week         SMALLINT    NOT NULL CHECK (week BETWEEN 1 AND 53),         -- ISO week number
    month        SMALLINT    NOT NULL CHECK (month BETWEEN 1 AND 12),
    month_name   VARCHAR(9)  NOT NULL,
    quarter      SMALLINT    NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    year         SMALLINT    NOT NULL,
    is_weekend   BOOLEAN     NOT NULL
);

-- Grain: one medicine category.
CREATE TABLE IF NOT EXISTS warehouse.dim_category (
    category_key   INTEGER      PRIMARY KEY,
    category_id    VARCHAR(10)  NOT NULL UNIQUE,          -- source/natural key
    category_name  VARCHAR(60)  NOT NULL
);

-- Grain: one medicine (product). demand_profile is generation metadata and is intentionally NOT loaded.
CREATE TABLE IF NOT EXISTS warehouse.dim_medicine (
    medicine_key   INTEGER       PRIMARY KEY,
    medicine_id    VARCHAR(10)   NOT NULL UNIQUE,         -- source/natural key
    medicine_name  VARCHAR(120)  NOT NULL,
    category_key   INTEGER       NOT NULL REFERENCES warehouse.dim_category (category_key),
    manufacturer   VARCHAR(80)   NOT NULL,
    dosage_form    VARCHAR(30)   NOT NULL,
    strength       VARCHAR(40)   NOT NULL,
    base_price     NUMERIC(10,2) NOT NULL CHECK (base_price > 0)
);

-- Grain: one pharmacy branch.
CREATE TABLE IF NOT EXISTS warehouse.dim_branch (
    branch_key   INTEGER      PRIMARY KEY,
    branch_id    VARCHAR(10)  NOT NULL UNIQUE,            -- source/natural key
    branch_name  VARCHAR(80)  NOT NULL,
    city         VARCHAR(60)  NOT NULL,
    area         VARCHAR(60)  NOT NULL
);

-- Grain: one supplier.
CREATE TABLE IF NOT EXISTS warehouse.dim_supplier (
    supplier_key   INTEGER      PRIMARY KEY,
    supplier_id    VARCHAR(10)  NOT NULL UNIQUE,          -- source/natural key
    supplier_name  VARCHAR(120) NOT NULL,
    city           VARCHAR(60)  NOT NULL
);

-- Grain: one manufacturing lot (batch) of one medicine from one supplier.
CREATE TABLE IF NOT EXISTS warehouse.dim_batch (
    batch_key         INTEGER       PRIMARY KEY,
    batch_id          VARCHAR(12)   NOT NULL UNIQUE,      -- source/natural key
    medicine_key      INTEGER       NOT NULL REFERENCES warehouse.dim_medicine (medicine_key),
    supplier_key      INTEGER       NOT NULL REFERENCES warehouse.dim_supplier (supplier_key),
    manufacture_date  DATE          NOT NULL,
    expiry_date       DATE          NOT NULL,
    initial_quantity  INTEGER       NOT NULL CHECK (initial_quantity > 0),
    purchase_price    NUMERIC(10,2) NOT NULL CHECK (purchase_price > 0),
    CHECK (manufacture_date < expiry_date)
);

-- ===========================================================================
-- FACTS
-- ===========================================================================

-- Grain: one medicine/batch line sold at one branch as part of one transaction.
-- transaction_id is a degenerate dimension; it repeats once per line, so it is NOT the primary key.
CREATE TABLE IF NOT EXISTS warehouse.fact_sales (
    sales_key           BIGINT        PRIMARY KEY,
    date_key            INTEGER       NOT NULL REFERENCES warehouse.dim_date (date_key),
    medicine_key        INTEGER       NOT NULL REFERENCES warehouse.dim_medicine (medicine_key),
    branch_key          INTEGER       NOT NULL REFERENCES warehouse.dim_branch (branch_key),
    batch_key           INTEGER       NOT NULL REFERENCES warehouse.dim_batch (batch_key),
    transaction_id      VARCHAR(12)   NOT NULL,
    quantity            INTEGER       NOT NULL CHECK (quantity > 0),
    unit_selling_price  NUMERIC(10,2) NOT NULL CHECK (unit_selling_price > 0),
    discount            NUMERIC(10,2) NOT NULL CHECK (discount >= 0),
    total_amount        NUMERIC(12,2) NOT NULL CHECK (total_amount >= 0),
    CHECK (total_amount = quantity * unit_selling_price - discount),
    -- enforces the grain; its leading column also serves basket lookups by transaction_id
    CONSTRAINT uq_fact_sales_grain UNIQUE (transaction_id, medicine_key, batch_key)
);

-- Grain: one batch delivery line: one batch received at one branch from one supplier.
CREATE TABLE IF NOT EXISTS warehouse.fact_purchase (
    purchase_key         BIGINT        PRIMARY KEY,
    date_key             INTEGER       NOT NULL REFERENCES warehouse.dim_date (date_key),
    medicine_key         INTEGER       NOT NULL REFERENCES warehouse.dim_medicine (medicine_key),
    branch_key           INTEGER       NOT NULL REFERENCES warehouse.dim_branch (branch_key),
    supplier_key         INTEGER       NOT NULL REFERENCES warehouse.dim_supplier (supplier_key),
    batch_key            INTEGER       NOT NULL REFERENCES warehouse.dim_batch (batch_key),
    purchase_id          VARCHAR(12)   NOT NULL UNIQUE,   -- degenerate dimension / source key
    quantity             INTEGER       NOT NULL CHECK (quantity > 0),
    unit_purchase_price  NUMERIC(10,2) NOT NULL CHECK (unit_purchase_price > 0),
    total_cost           NUMERIC(14,2) NOT NULL CHECK (total_cost >= 0),
    CHECK (total_cost = quantity * unit_purchase_price)
);

-- Grain: end-of-day inventory state of one medicine at one branch on one calendar date
-- (periodic snapshot, dense: one row for every date x branch x medicine; closing_quantity = 0 on stockout days).
-- Derived by the ETL from purchases, sales and batch expiry; there is no inventory source file.
-- Semi-additive: sum across branches/medicines is valid, sum across dates is NOT (use last day or average).
CREATE TABLE IF NOT EXISTS warehouse.fact_inventory (
    date_key               INTEGER       NOT NULL REFERENCES warehouse.dim_date (date_key),
    branch_key             INTEGER       NOT NULL REFERENCES warehouse.dim_branch (branch_key),
    medicine_key           INTEGER       NOT NULL REFERENCES warehouse.dim_medicine (medicine_key),
    opening_quantity       INTEGER       NOT NULL CHECK (opening_quantity >= 0),
    purchased_quantity     INTEGER       NOT NULL CHECK (purchased_quantity >= 0),   -- flow, additive
    sold_quantity          INTEGER       NOT NULL CHECK (sold_quantity >= 0),        -- flow, additive
    expired_quantity       INTEGER       NOT NULL CHECK (expired_quantity >= 0),     -- flow, additive
    closing_quantity       INTEGER       NOT NULL CHECK (closing_quantity >= 0),     -- state, semi-additive
    closing_value_at_cost  NUMERIC(14,2) NOT NULL CHECK (closing_value_at_cost >= 0), -- state, semi-additive
    PRIMARY KEY (date_key, branch_key, medicine_key),
    CHECK (opening_quantity + purchased_quantity - sold_quantity - expired_quantity = closing_quantity)
);

-- ===========================================================================
-- INDEXES (chosen for the expected OLAP access paths; primary/unique keys already index themselves)
-- ===========================================================================
-- fact_sales: each dimension key is a filter/join/group-by path (time series, product mix, branch analysis,
-- batch/expiry joins). Basket lookups by transaction_id use uq_fact_sales_grain.
CREATE INDEX IF NOT EXISTS ix_fact_sales_date      ON warehouse.fact_sales (date_key);
CREATE INDEX IF NOT EXISTS ix_fact_sales_medicine  ON warehouse.fact_sales (medicine_key);
CREATE INDEX IF NOT EXISTS ix_fact_sales_branch    ON warehouse.fact_sales (branch_key);
CREATE INDEX IF NOT EXISTS ix_fact_sales_batch     ON warehouse.fact_sales (batch_key);

-- fact_purchase: supplier/medicine purchasing analysis, receipt timing, and batch stock reconstruction.
CREATE INDEX IF NOT EXISTS ix_fact_purchase_date     ON warehouse.fact_purchase (date_key);
CREATE INDEX IF NOT EXISTS ix_fact_purchase_medicine ON warehouse.fact_purchase (medicine_key);
CREATE INDEX IF NOT EXISTS ix_fact_purchase_branch   ON warehouse.fact_purchase (branch_key);
CREATE INDEX IF NOT EXISTS ix_fact_purchase_supplier ON warehouse.fact_purchase (supplier_key);
CREATE INDEX IF NOT EXISTS ix_fact_purchase_batch    ON warehouse.fact_purchase (batch_key);

-- fact_inventory: the primary key (date, branch, medicine) serves "state on a date" lookups and date slices;
-- this index serves a medicine's (or branch+medicine's) stock history over time.
CREATE INDEX IF NOT EXISTS ix_fact_inventory_medicine_branch ON warehouse.fact_inventory (medicine_key, branch_key, date_key);

-- dimensions: lookups/joins by attribute
CREATE INDEX IF NOT EXISTS ix_dim_medicine_category ON warehouse.dim_medicine (category_key);
CREATE INDEX IF NOT EXISTS ix_dim_batch_medicine    ON warehouse.dim_batch (medicine_key);
CREATE INDEX IF NOT EXISTS ix_dim_batch_supplier    ON warehouse.dim_batch (supplier_key);
CREATE INDEX IF NOT EXISTS ix_dim_batch_expiry      ON warehouse.dim_batch (expiry_date);
