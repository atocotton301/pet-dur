-- 반려동물 약·음식 안전 조회 DB (SQLite). docs/phase1_report.md ERD 기준 + 약물군 소속.
PRAGMA foreign_keys = ON;

CREATE TABLE species_group (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE species (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name_ko TEXT NOT NULL,
  group_id INTEGER NOT NULL REFERENCES species_group(id), sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE substance_type (code TEXT PRIMARY KEY, label_ko TEXT NOT NULL);
CREATE TABLE substance (
  id INTEGER PRIMARY KEY,
  key TEXT NOT NULL UNIQUE,              -- 정규화한 영문명
  name_ko TEXT NOT NULL, name_en TEXT,
  type_code TEXT NOT NULL REFERENCES substance_type(code)
);
CREATE TABLE substance_alias (
  id INTEGER PRIMARY KEY,
  substance_id INTEGER NOT NULL REFERENCES substance(id),
  alias TEXT NOT NULL, alias_norm TEXT NOT NULL,
  alias_type TEXT NOT NULL CHECK (alias_type IN ('표준명','영문','동의어','성분표기','오타')),
  UNIQUE (substance_id, alias_norm)
);
CREATE INDEX ix_alias_norm ON substance_alias(alias_norm);

CREATE TABLE source (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL UNIQUE,
  tier INTEGER NOT NULL CHECK (tier IN (1,2,3))
);
-- 약물군(class) → 소속 성분(member). 둘 다 substance.
CREATE TABLE substance_class_member (
  class_id INTEGER NOT NULL REFERENCES substance(id),
  member_id INTEGER NOT NULL REFERENCES substance(id),
  source_id INTEGER NOT NULL REFERENCES source(id),
  checked_on TEXT NOT NULL,
  PRIMARY KEY (class_id, member_id)
);

CREATE TABLE company (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE human_drug_product (
  item_seq TEXT PRIMARY KEY, name TEXT NOT NULL, name_norm TEXT NOT NULL,
  company_id INTEGER REFERENCES company(id)
);
CREATE TABLE product_ingredient (
  item_seq TEXT NOT NULL REFERENCES human_drug_product(item_seq),
  raw_name TEXT NOT NULL,
  substance_id INTEGER REFERENCES substance(id),   -- NULL = 규칙 DB에 없는 성분
  PRIMARY KEY (item_seq, raw_name)
);
CREATE TABLE vet_drug_product (
  id INTEGER PRIMARY KEY, permit_no TEXT NOT NULL, name TEXT NOT NULL, name_norm TEXT NOT NULL,
  name_en TEXT, company_id INTEGER REFERENCES company(id),
  usage_type TEXT, permit_date TEXT, dosage_form TEXT
);
CREATE INDEX ix_vet_name ON vet_drug_product(name_norm);

CREATE TABLE risk_level (code TEXT PRIMARY KEY, label_ko TEXT NOT NULL, severity INTEGER NOT NULL);
CREATE TABLE interaction_level (code TEXT PRIMARY KEY, label_ko TEXT NOT NULL, severity INTEGER NOT NULL);
CREATE TABLE mechanism (id INTEGER PRIMARY KEY, text TEXT NOT NULL UNIQUE);
CREATE TABLE symptom (id INTEGER PRIMARY KEY, text TEXT NOT NULL UNIQUE);
CREATE TABLE first_aid_action (id INTEGER PRIMARY KEY, text TEXT NOT NULL UNIQUE);

CREATE TABLE toxicity_rule (
  id INTEGER PRIMARY KEY,
  substance_id INTEGER NOT NULL REFERENCES substance(id),
  species_id INTEGER NOT NULL REFERENCES species(id),
  risk_code TEXT NOT NULL REFERENCES risk_level(code),
  mechanism_id INTEGER REFERENCES mechanism(id),
  review_status TEXT NOT NULL DEFAULT '미감수' CHECK (review_status IN ('미감수','수의사 검토중','감수완료')),
  UNIQUE (substance_id, species_id)
);
CREATE TABLE rule_symptom (
  rule_id INTEGER NOT NULL REFERENCES toxicity_rule(id), symptom_id INTEGER NOT NULL REFERENCES symptom(id),
  PRIMARY KEY (rule_id, symptom_id)
);
CREATE TABLE rule_action (
  rule_id INTEGER NOT NULL REFERENCES toxicity_rule(id), action_id INTEGER NOT NULL REFERENCES first_aid_action(id),
  step_order INTEGER NOT NULL, PRIMARY KEY (rule_id, action_id)
);
CREATE TABLE rule_source (
  rule_id INTEGER NOT NULL REFERENCES toxicity_rule(id), source_id INTEGER NOT NULL REFERENCES source(id),
  checked_on TEXT NOT NULL, evidence TEXT, PRIMARY KEY (rule_id, source_id)
);

CREATE TABLE interaction_rule (
  id INTEGER PRIMARY KEY,
  substance_a_id INTEGER NOT NULL REFERENCES substance(id),
  substance_b_id INTEGER NOT NULL REFERENCES substance(id),
  species_id INTEGER NOT NULL REFERENCES species(id),
  level_code TEXT NOT NULL REFERENCES interaction_level(code),
  mechanism_id INTEGER REFERENCES mechanism(id),
  advice_id INTEGER REFERENCES first_aid_action(id),
  review_status TEXT NOT NULL DEFAULT '미감수',
  CHECK (substance_a_id <= substance_b_id),
  UNIQUE (substance_a_id, substance_b_id, species_id)
);
CREATE TABLE interaction_source (
  rule_id INTEGER NOT NULL REFERENCES interaction_rule(id), source_id INTEGER NOT NULL REFERENCES source(id),
  checked_on TEXT NOT NULL, evidence TEXT, PRIMARY KEY (rule_id, source_id)
);

CREATE TABLE vet_clinic (
  mgmt_no TEXT PRIMARY KEY, name TEXT NOT NULL, road_addr TEXT, jibun_addr TEXT, tel TEXT,
  lat REAL NOT NULL, lng REAL NOT NULL,
  is_24h INTEGER,                 -- NULL = 모름 (데이터에 없음)
  name_suggests_24h INTEGER NOT NULL DEFAULT 0,
  treats_exotic INTEGER,          -- NULL = 모름
  updated_at TEXT
);
CREATE INDEX ix_clinic_lat ON vet_clinic(lat);

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);

-- 장소 탭: 유치원·호텔(동물위탁관리업), 미용(동물미용업), 동반 장소, 공원 등. 동물병원은 vet_clinic을 그대로 쓴다.
CREATE TABLE place_category (code TEXT PRIMARY KEY, label_ko TEXT NOT NULL, sort_order INTEGER NOT NULL);
CREATE TABLE place (
  id INTEGER PRIMARY KEY,
  category_code TEXT NOT NULL REFERENCES place_category(code),
  ext_id TEXT NOT NULL,                 -- 원본 데이터의 관리번호 등
  name TEXT NOT NULL, address TEXT, tel TEXT,
  lat REAL NOT NULL, lng REAL NOT NULL,
  dataset TEXT NOT NULL, source_url TEXT NOT NULL, updated_at TEXT,
  UNIQUE (category_code, ext_id)
);
CREATE INDEX ix_place_lat ON place(lat);
