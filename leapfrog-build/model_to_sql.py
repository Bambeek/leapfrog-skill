#!/usr/bin/env python3
"""Draft Postgres SQL from a scout data model. Standard library only.

    model_to_sql.py leapfrog/recon/model.md --out leapfrog/schema.sql

Model format (lines starting with # are comments):

    entity Booking
      owner user                      -> user_id uuid FK users
      event_type -> EventType         -> event_type_id uuid FK event_types
      start_at time                   -> timestamptz
      status enum(confirmed,cancelled)
      price money?                    -> price_cents integer + price_currency, nullable
      answers json

Types: text int bool time date json money enum(...) -> Entity, ? for nullable.
Every table gets id, created_at, updated_at; every foreign key gets an index.
`on delete` is cascade with a TODO: decide each one by hand.
"""

import argparse
import re
import sys

TYPES = {
    "text": "text", "int": "integer", "bigint": "bigint", "bool": "boolean", "float": "double precision",
    "time": "timestamptz", "date": "date", "json": "jsonb", "uuid": "uuid", "decimal": "numeric",
}
DEFAULTS = {"bool": "false", "json": "'{}'"}


def snake(name):
    s = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name)
    return re.sub(r"[^a-z0-9_]", "_", s.lower()).strip("_")


def plural(name):
    if name.endswith("y") and not name.endswith(("ay", "ey", "oy", "uy")):
        return name[:-1] + "ies"
    if name.endswith(("s", "x", "z", "ch", "sh")):
        return name + "es"
    return name + "s"


def table_of(entity):
    return plural(snake(entity))


def parse(text):
    entities, cur = [], None
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        m = re.match(r"\s*entity\s+([A-Za-z][A-Za-z0-9_]*)\s*$", line)
        if m:
            cur = {"name": m.group(1), "fields": []}
            entities.append(cur)
            continue
        if cur is None:
            raise ValueError("line %d: field before any 'entity'" % n)
        m = re.match(r"\s*([a-z_][a-z0-9_]*)\s+(.+?)\s*$", line)
        if not m:
            raise ValueError("line %d: cannot read %r" % (n, raw.strip()))
        name, typ = m.group(1), m.group(2)
        nullable = typ.endswith("?")
        typ = typ.rstrip("?").strip()
        cur["fields"].append({"name": name, "type": typ, "null": nullable, "line": n})
    return entities


def column_sql(table, f, known):
    nn = "" if f["null"] else " not null"
    t = f["type"]
    cols, idx, fks = [], [], []
    ref = re.match(r"->\s*([A-Za-z][A-Za-z0-9_]*)$", t)
    if t == "user" or ref:
        target = "users" if t == "user" else table_of(ref.group(1))
        col = "user_id" if t == "user" else f["name"] + "_id"
        if ref and ref.group(1) not in known:
            fks.append("-- WARNING: %s references %s, which is not in the model" % (col, ref.group(1)))
        cols.append("  %s uuid%s references %s(id) on delete cascade -- TODO decide on delete" % (col, nn, target))
        idx.append("create index on %s (%s);" % (table, col))
    elif t == "money":
        cols.append("  %s_cents integer%s check (%s_cents >= 0)" % (f["name"], nn, f["name"]))
        cols.append("  %s_currency char(3)%s default 'USD'" % (f["name"], nn))
    elif t.startswith("enum("):
        vals = [v.strip() for v in t[5:-1].split(",") if v.strip()]
        if not t.endswith(")") or not vals:
            raise ValueError("line %d: bad enum %r" % (f["line"], t))
        quoted = ",".join("'%s'" % v.replace("'", "''") for v in vals)
        default = "" if f["null"] else " default '%s'" % vals[0]
        cols.append("  %s text%s%s check (%s in (%s))" % (f["name"], nn, default, f["name"], quoted))
        idx.append("create index on %s (%s);" % (table, f["name"]))
    elif t in TYPES:
        default = " default %s" % DEFAULTS[t] if t in DEFAULTS and not f["null"] else ""
        cols.append("  %s %s%s%s" % (f["name"], TYPES[t], nn, default))
        if t in ("time", "date"):
            idx.append("create index on %s (%s);" % (table, f["name"]))
    else:
        raise ValueError("line %d: unknown type %r" % (f["line"], t))
    return cols, idx, fks


def to_sql(entities):
    known = {e["name"] for e in entities}
    has_users = "User" in known
    out = ["-- Draft from model_to_sql.py. Review every TODO before the first migration.",
           "create extension if not exists pgcrypto;", ""]
    if any(f["type"] == "user" for e in entities for f in e["fields"]) and not has_users:
        out.append("-- WARNING: 'owner user' used but there is no 'entity User'; expects a users table (auth).")
        out.append("")
    # Referenced tables first so foreign keys resolve.
    order, placed = [], set()

    def visit(e, stack=()):
        if e["name"] in placed or e["name"] in stack:
            return
        for f in e["fields"]:
            m = re.match(r"->\s*([A-Za-z][A-Za-z0-9_]*)$", f["type"])
            dep = m.group(1) if m else ("User" if f["type"] == "user" else None)
            if dep and dep != e["name"]:
                target = next((x for x in entities if x["name"] == dep), None)
                if target:
                    visit(target, stack + (e["name"],))
        placed.add(e["name"])
        order.append(e)

    for e in entities:
        visit(e)

    for e in order:
        table = table_of(e["name"])
        cols = ["  id uuid primary key default gen_random_uuid()"]
        idx, notes = [], []
        for f in e["fields"]:
            c, i, n = column_sql(table, f, known)
            cols += c
            idx += i
            notes += n
        cols += ["  created_at timestamptz not null default now()", "  updated_at timestamptz not null default now()"]
        out += notes
        out.append("create table %s (\n%s\n);" % (table, ",\n".join(cols)))
        out += idx
        out.append("")
    out.append("-- TODO access rules: enable row level security per table, or one authorisation check per query.")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Draft Postgres SQL from a Leapfrog data model")
    ap.add_argument("model")
    ap.add_argument("--out", help="write here instead of stdout")
    args = ap.parse_args(argv)
    with open(args.model, encoding="utf-8") as f:
        text = f.read()
    try:
        entities = parse(text)
        sql = to_sql(entities)
    except ValueError as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(sql)
        print("%d tables, %d TODOs -> %s" % (len(entities), sql.count("TODO"), args.out))
    else:
        sys.stdout.write(sql)
    return 0


if __name__ == "__main__":
    sys.exit(main())
