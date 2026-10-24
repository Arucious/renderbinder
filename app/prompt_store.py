"""Searchable prompt documents, independent of the media that carries them."""

from __future__ import annotations

import hashlib
import heapq
import json
import re

from .similarity import prepare_prompt, text_similarity


def text_hash(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return hashlib.sha256(text.encode()).hexdigest() if text else None


def group_hash(text, scope):
    digest = text_hash(text)
    return (
        digest
        if scope == "positive"
        else hashlib.sha256((scope + ":" + (digest or "")).encode()).hexdigest()
    )


class PromptStore:
    def __init__(self, database, columns):
        self.database, self.columns = database, columns
        with database.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS prompt_entries (
                    id TEXT PRIMARY KEY, image_id TEXT NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                    scope TEXT NOT NULL, label TEXT NOT NULL, text TEXT NOT NULL,
                    group_hash TEXT NOT NULL, text_hash TEXT NOT NULL, start REAL, end REAL,
                    provenance TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS prompts_media ON prompt_entries(image_id);
                CREATE INDEX IF NOT EXISTS prompts_groups ON prompt_entries(group_hash);
                CREATE INDEX IF NOT EXISTS prompts_scope ON prompt_entries(scope,group_hash);
                CREATE VIRTUAL TABLE IF NOT EXISTS prompt_search USING fts5(entry_id UNINDEXED,text,label,tokenize='unicode61 remove_diacritics 2');
                CREATE TRIGGER IF NOT EXISTS prompts_insert AFTER INSERT ON prompt_entries BEGIN
                    INSERT INTO prompt_search VALUES(new.id,new.text,new.label);
                END;
                CREATE TRIGGER IF NOT EXISTS prompts_delete AFTER DELETE ON prompt_entries BEGIN
                    DELETE FROM prompt_search WHERE entry_id=old.id;
                END;
            """)
            # Existing image libraries remain searchable before the background parser upgrade.
            for row in db.execute(
                "SELECT id,positive FROM images WHERE positive<>'' AND id NOT IN (SELECT image_id FROM prompt_entries)"
            ).fetchall():
                self.replace(
                    db,
                    row["id"],
                    [
                        {
                            "key": "positive",
                            "scope": "positive",
                            "label": "Positive prompt",
                            "text": row["positive"],
                        }
                    ],
                )

    @staticmethod
    def replace(db, image_id, documents):
        db.execute("DELETE FROM prompt_entries WHERE image_id=?", (image_id,))
        seen = set()
        for index, document in enumerate(documents):
            text, scope = document.get("text", ""), document.get("scope", "positive")
            if not isinstance(text, str) or not text.strip():
                continue
            entry_id = hashlib.sha256(
                (image_id + ":" + str(document.get("key", index))).encode()
            ).hexdigest()[:32]
            if entry_id in seen:
                continue
            seen.add(entry_id)
            db.execute(
                "INSERT INTO prompt_entries VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    entry_id,
                    image_id,
                    scope,
                    document.get("label", scope.title()),
                    text,
                    group_hash(text, scope),
                    text_hash(text),
                    document.get("start"),
                    document.get("end"),
                    json.dumps(
                        {
                            **document.get("provenance", {}),
                            "context": {
                                key: value
                                for key, value in document.items()
                                if key
                                not in {
                                    "key",
                                    "scope",
                                    "label",
                                    "text",
                                    "start",
                                    "end",
                                    "provenance",
                                }
                            },
                        }
                    ),
                ),
            )

    def documents(self, image_id):
        with self.database.connect() as db:
            rows = db.execute(
                "SELECT * FROM prompt_entries WHERE image_id=? ORDER BY CASE scope WHEN 'global' THEN 0 WHEN 'positive' THEN 1 ELSE 2 END,start,id",
                (image_id,),
            ).fetchall()
            return [
                {
                    **dict(row),
                    "prompt_id": row["id"],
                    "positive_hash": row["group_hash"],
                    "positive": row["text"],
                    "provenance": json.loads(row["provenance"]),
                }
                for row in rows
            ]

    def text(self, entry_id=None, *, image_id=None):
        with self.database.connect() as db:
            row = db.execute(
                "SELECT p.*,i.path FROM prompt_entries p JOIN images i ON i.id=p.image_id WHERE "
                + ("p.id=?" if entry_id else "p.image_id=?")
                + " ORDER BY CASE p.scope WHEN 'global' THEN 0 WHEN 'positive' THEN 1 ELSE 2 END,p.start LIMIT 1",
                (entry_id or image_id,),
            ).fetchone()
            return (
                {
                    **dict(row),
                    "id": row["image_id"],
                    "prompt_id": row["id"],
                    "positive_hash": row["group_hash"],
                    "positive": row["text"],
                }
                if row
                else None
            )

    def render(self, row):
        item = self.database.summary(row)
        for key, target in (
            ("prompt_positive", "positive"),
            ("prompt_group_hash", "positive_hash"),
        ):
            item[target] = item.pop(key)
        return item

    @staticmethod
    def cte(joins, clause):
        return (
            "WITH matches AS (SELECT p.id,p.image_id,p.group_hash,"
            "row_number() OVER (PARTITION BY p.group_hash ORDER BY i.sort_date DESC,i.id,p.id) representative"
            + joins
            + clause
            + "),counts AS (SELECT group_hash,count(DISTINCT image_id) image_count FROM matches GROUP BY group_hash) "
        )

    @property
    def selected(self):
        return (
            self.columns
            + ",p.id prompt_id,p.scope,p.label,p.start,p.end,p.text_hash,substr(p.text,1,600) prompt_positive,p.group_hash prompt_group_hash,c.image_count"
        )

    def list(
        self,
        where,
        args,
        *,
        q="",
        exact=False,
        scope="",
        order="i.sort_date DESC,i.id",
        offset=0,
        limit=60,
    ):
        where, args = list(where), list(args)
        if scope:
            where.append("p.scope=?")
            args.append(scope)
        if q.strip():
            asset_text = (
                "i.filename||' '||i.models||' '||i.loras||' '||coalesce(a.tags,'')"
            )
            if exact:
                where.append(
                    f"instr(casefold(p.text||' '||{asset_text}),casefold(?))>0"
                )
                args.append(q.strip())
            else:
                terms = re.findall(r"[^\W_]+", q)
                where.append(
                    f"(p.id IN (SELECT entry_id FROM prompt_search WHERE prompt_search MATCH ?) OR instr(casefold({asset_text}),casefold(?))>0)"
                    if terms
                    else "0"
                )
                if terms:
                    args.extend(
                        [" AND ".join('"' + t + '"' for t in terms[:40]), q.strip()]
                    )
        joins = " FROM prompt_entries p JOIN images i ON i.id=p.image_id LEFT JOIN library.annotations a USING(path_key)"
        clause = " WHERE " + " AND ".join(where) if where else ""
        with self.database.connect() as db:
            total, media_total = db.execute(
                "SELECT count(DISTINCT p.group_hash),count(DISTINCT i.id)"
                + joins
                + clause,
                args,
            ).fetchone()
            rows = db.execute(
                self.cte(joins, clause)
                + "SELECT "
                + self.selected
                + " FROM matches m JOIN prompt_entries p ON p.id=m.id JOIN images i ON i.id=p.image_id JOIN counts c ON c.group_hash=p.group_hash LEFT JOIN library.annotations a USING(path_key) WHERE m.representative=1 ORDER BY "
                + order
                + ",p.id LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
            return {
                "items": [self.render(row) for row in rows],
                "total": total,
                "image_total": media_total,
                "offset": offset,
                "limit": limit,
            }

    def embeddings(self, roots):
        placeholders = ",".join("?" for _ in roots) or "NULL"
        with self.database.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    f"SELECT p.text_hash positive_hash,min(p.text) positive FROM prompt_entries p JOIN images i ON i.id=p.image_id WHERE i.root IN ({placeholders}) GROUP BY p.text_hash",
                    roots,
                )
            ]

    def similar(
        self,
        source,
        roots,
        *,
        limit=12,
        minimum=0.45,
        semantic_scores=None,
        mode="hybrid",
        same_scope=True,
    ):
        if not source:
            return None
        placeholders = ",".join("?" for _ in roots) or "NULL"
        prepared, sampled = prepare_prompt(source["positive"])
        result = {
            "items": [],
            "total": 0,
            "compared": 0,
            "minimum": minimum,
            "source_sampled": sampled,
            "method": mode if semantic_scores else "text",
            "scope": source["scope"] if same_scope else "all",
        }
        if mode == "semantic" and not semantic_scores:
            return result
        with self.database.connect() as db:
            allowed = db.execute(
                f"SELECT 1 FROM images WHERE id=? AND root IN ({placeholders})",
                [source["id"], *roots],
            ).fetchone()
            if not allowed:
                return None
            where = [f"i.root IN ({placeholders})", "p.group_hash<>?"]
            args = [*roots, source["positive_hash"]]
            if same_scope:
                where.append("p.scope=?")
                args.append(source["scope"])
            joins = " FROM prompt_entries p JOIN images i ON i.id=p.image_id"
            cte = self.cte(joins, " WHERE " + " AND ".join(where))
            rows = db.execute(
                cte
                + "SELECT p.*,i.sort_date,c.image_count FROM matches m JOIN prompt_entries p ON p.id=m.id JOIN images i ON i.id=p.image_id JOIN counts c ON c.group_hash=p.group_hash WHERE m.representative=1",
                args,
            )
            best = []
            for row in rows:
                candidate, candidate_sampled = prepare_prompt(row["text"])
                lexical = text_similarity(prepared, candidate, 0)
                semantic = (semantic_scores or {}).get(row["text_hash"])
                if mode == "semantic" and semantic is None:
                    continue
                score = (
                    lexical
                    if mode == "text" or semantic is None
                    else semantic
                    if mode == "semantic"
                    else 0.65 * semantic + 0.35 * lexical
                )
                result["compared"] += 1
                if score < minimum or score == 0:
                    continue
                result["total"] += 1
                item = (
                    score,
                    row["sort_date"],
                    row["id"],
                    row["group_hash"],
                    row["image_count"],
                    candidate_sampled or sampled,
                    lexical,
                    semantic,
                )
                if len(best) < limit:
                    heapq.heappush(best, item)
                elif item > best[0]:
                    heapq.heapreplace(best, item)
            for (
                score,
                _,
                entry_id,
                expected_hash,
                count,
                sample,
                lexical,
                semantic,
            ) in sorted(best, reverse=True):
                row = db.execute(
                    "SELECT "
                    + self.selected
                    + " FROM prompt_entries p JOIN images i ON i.id=p.image_id JOIN (SELECT ? image_count) c LEFT JOIN library.annotations a USING(path_key) WHERE p.id=? AND p.group_hash=?",
                    (count, entry_id, expected_hash),
                ).fetchone()
                if row:
                    result["items"].append(
                        {
                            **self.render(row),
                            "similarity": round(score, 6),
                            "text_similarity": round(lexical, 6),
                            "semantic_similarity": round(semantic, 6)
                            if semantic is not None
                            else None,
                            "sampled": sample,
                        }
                    )
            return result
