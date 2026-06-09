-- Highway Bites drive-thru menu schema.
-- Money is stored as integer paise (1 INR = 100 paise) — never floats.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS menu_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    category        TEXT    NOT NULL CHECK (category IN ('burger','side','drink','dessert')),
    subcategory     TEXT,
    is_veg          INTEGER NOT NULL CHECK (is_veg IN (0,1)),
    price_paise     INTEGER NOT NULL CHECK (price_paise >= 0),
    description     TEXT,
    available       INTEGER NOT NULL DEFAULT 1 CHECK (available IN (0,1))
);

CREATE INDEX IF NOT EXISTS idx_menu_items_category    ON menu_items(category);
CREATE INDEX IF NOT EXISTS idx_menu_items_subcategory ON menu_items(subcategory);
CREATE INDEX IF NOT EXISTS idx_menu_items_is_veg      ON menu_items(is_veg);

CREATE TABLE IF NOT EXISTS combos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    is_veg          INTEGER NOT NULL CHECK (is_veg IN (0,1)),
    price_paise     INTEGER NOT NULL CHECK (price_paise >= 0),
    description     TEXT,
    available       INTEGER NOT NULL DEFAULT 1 CHECK (available IN (0,1))
);

CREATE INDEX IF NOT EXISTS idx_combos_is_veg ON combos(is_veg);

CREATE TABLE IF NOT EXISTS combo_items (
    combo_id        INTEGER NOT NULL,
    item_id         INTEGER NOT NULL,
    quantity        INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    PRIMARY KEY (combo_id, item_id),
    FOREIGN KEY (combo_id) REFERENCES combos(id)      ON DELETE CASCADE,
    FOREIGN KEY (item_id)  REFERENCES menu_items(id)  ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS modifications (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    name                    TEXT    NOT NULL UNIQUE,
    price_delta_paise       INTEGER NOT NULL DEFAULT 0,
    applies_to_category     TEXT CHECK (applies_to_category IN ('burger','side','drink','dessert') OR applies_to_category IS NULL),
    description             TEXT
);

CREATE TABLE IF NOT EXISTS promotions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT    NOT NULL UNIQUE,
    description         TEXT    NOT NULL,
    -- 'percent' = discount_value is % off (0-100)
    -- 'flat_paise' = discount_value is paise off the whole order
    -- 'combo_price_paise' = discount_value is the bundled price for a matching item set
    discount_type       TEXT    NOT NULL CHECK (discount_type IN ('percent','flat_paise','combo_price_paise')),
    discount_value      INTEGER NOT NULL,
    -- Minimum order subtotal (paise) required to apply this promotion. NULL = no threshold.
    -- Only enforced for 'percent' and 'flat_paise' promotions.
    min_subtotal_paise  INTEGER,
    -- JSON-encoded match condition. REQUIRED for combo_price_paise promotions,
    -- IGNORED for percent / flat_paise. Supported shapes:
    --   {"type":"specific_items","items":["Masala Chai","Garlic Bread (2 pc)"]}
    --   {"type":"any_n_in_category","n":2,"category":"burger","is_veg":true}
    condition_json      TEXT,
    active              INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1))
);

CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    subtotal_paise  INTEGER NOT NULL CHECK (subtotal_paise >= 0),
    discount_paise  INTEGER NOT NULL DEFAULT 0 CHECK (discount_paise >= 0),
    total_paise     INTEGER NOT NULL CHECK (total_paise >= 0),
    promotion_id    INTEGER,
    status          TEXT    NOT NULL DEFAULT 'submitted' CHECK (status IN ('submitted','cancelled')),
    FOREIGN KEY (promotion_id) REFERENCES promotions(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS order_lines (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id            INTEGER NOT NULL,
    item_id             INTEGER,
    combo_id            INTEGER,
    quantity            INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    modifications_json  TEXT NOT NULL DEFAULT '[]',
    line_total_paise    INTEGER NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id)     ON DELETE CASCADE,
    FOREIGN KEY (item_id)  REFERENCES menu_items(id) ON DELETE RESTRICT,
    FOREIGN KEY (combo_id) REFERENCES combos(id)     ON DELETE RESTRICT,
    CHECK ((item_id IS NOT NULL) <> (combo_id IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_order_lines_order ON order_lines(order_id);
