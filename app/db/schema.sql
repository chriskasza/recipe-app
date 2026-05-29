-- Stage 2 schema. Idempotent rebuild = drop the DB file and re-run sync.
-- All FK cascades flow off `recipes`; the normalized name tables (ingredients, tags,
-- meal_types, dietary_flags, equipment) keep their rows so id reuse is stable across syncs.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE recipes (
  id TEXT PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  summary TEXT,
  cuisine TEXT,
  servings INTEGER,
  prep_minutes INTEGER,
  cook_minutes INTEGER,
  total_minutes INTEGER,
  source_url TEXT,
  source_attribution TEXT,
  archived INTEGER NOT NULL DEFAULT 0,
  favorite INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  file_path TEXT NOT NULL,
  file_mtime REAL NOT NULL,
  body_markdown TEXT NOT NULL,           -- raw body for FTS + future AI grounding
  ingredient_names TEXT NOT NULL DEFAULT '',  -- space-joined for FTS indexing
  frontmatter_json TEXT NOT NULL         -- normalized frontmatter for fast reads
);
CREATE INDEX recipes_updated ON recipes(updated_at);

CREATE TABLE ingredients (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL
);
CREATE TABLE recipe_ingredients (
  recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  ingredient_id INTEGER NOT NULL REFERENCES ingredients(id),
  qty REAL,
  unit TEXT,
  prep TEXT,
  optional INTEGER NOT NULL DEFAULT 0,
  original_text TEXT NOT NULL,
  PRIMARY KEY (recipe_id, position)
);
CREATE INDEX recipe_ingredients_ingredient ON recipe_ingredients(ingredient_id);

CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
CREATE TABLE recipe_tags (
  recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
  tag_id INTEGER NOT NULL REFERENCES tags(id),
  PRIMARY KEY (recipe_id, tag_id)
);

CREATE TABLE meal_types (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
CREATE TABLE recipe_meal_types (
  recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
  meal_type_id INTEGER NOT NULL REFERENCES meal_types(id),
  PRIMARY KEY (recipe_id, meal_type_id)
);

CREATE TABLE dietary_flags (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
CREATE TABLE recipe_dietary (
  recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
  dietary_id INTEGER NOT NULL REFERENCES dietary_flags(id),
  PRIMARY KEY (recipe_id, dietary_id)
);

CREATE TABLE equipment (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
CREATE TABLE recipe_equipment (
  recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
  equipment_id INTEGER NOT NULL REFERENCES equipment(id),
  PRIMARY KEY (recipe_id, equipment_id)
);

CREATE TABLE sync_runs (
  id INTEGER PRIMARY KEY,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  files_seen INTEGER NOT NULL DEFAULT 0,
  files_changed INTEGER NOT NULL DEFAULT 0,
  files_removed INTEGER NOT NULL DEFAULT 0,
  errors_json TEXT
);

-- FTS5 over the recipe content. External-content mode keeps the index lean.
-- ``ingredient_names`` is stored on `recipes` and refreshed on every upsert.
CREATE VIRTUAL TABLE recipes_fts USING fts5(
  title,
  summary,
  body_markdown,
  ingredient_names,
  content='recipes',
  content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER recipes_ai AFTER INSERT ON recipes BEGIN
  INSERT INTO recipes_fts(rowid, title, summary, body_markdown, ingredient_names)
  VALUES (new.rowid, new.title, COALESCE(new.summary, ''), new.body_markdown, new.ingredient_names);
END;

CREATE TRIGGER recipes_ad AFTER DELETE ON recipes BEGIN
  INSERT INTO recipes_fts(recipes_fts, rowid, title, summary, body_markdown, ingredient_names)
  VALUES ('delete', old.rowid, old.title, COALESCE(old.summary, ''), old.body_markdown, old.ingredient_names);
END;

CREATE TRIGGER recipes_au AFTER UPDATE ON recipes BEGIN
  INSERT INTO recipes_fts(recipes_fts, rowid, title, summary, body_markdown, ingredient_names)
  VALUES ('delete', old.rowid, old.title, COALESCE(old.summary, ''), old.body_markdown, old.ingredient_names);
  INSERT INTO recipes_fts(rowid, title, summary, body_markdown, ingredient_names)
  VALUES (new.rowid, new.title, COALESCE(new.summary, ''), new.body_markdown, new.ingredient_names);
END;
