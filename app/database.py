from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

from .prompt_store import PromptStore

IMAGE_SUMMARY_COLUMNS = "i.id,i.filename,i.folder,i.root,i.width,i.height,i.size,i.model,i.loras,i.seeds,substr(i.positive,1,600) positive,substr(i.negative,1,200) negative,i.sort_date,i.generated_at,i.confidence,i.workflow_hash,i.configuration_hash,i.positive_hash,i.media_kind,i.duration,i.fps,i.technical,(SELECT count(*) FROM prompt_entries ep WHERE ep.image_id=i.id AND ep.scope='shot') shot_count,coalesce(a.favorite,0) favorite,coalesce(a.tags,'[]') tags"


def prompt_hash(text: str) -> str | None:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return (
        hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else None
    )


class Database:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "index.sqlite3"
        self.user_path = data_dir / "library.sqlite3"
        self.write_lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA library.journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS images (
                    id TEXT PRIMARY KEY, path_key TEXT UNIQUE NOT NULL, path TEXT NOT NULL,
                    root TEXT NOT NULL, folder TEXT NOT NULL, filename TEXT NOT NULL,
                    size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, created_at REAL NOT NULL,
                    modified_at REAL NOT NULL, sort_date REAL NOT NULL, generated_at REAL,
                    width INTEGER NOT NULL, height INTEGER NOT NULL, model TEXT, models TEXT NOT NULL,
                    loras TEXT NOT NULL, seeds TEXT NOT NULL, positive TEXT NOT NULL, negative TEXT NOT NULL,
                    metadata TEXT NOT NULL, confidence TEXT NOT NULL, workflow_hash TEXT,
                    configuration_hash TEXT, thumbnail TEXT NOT NULL, version INTEGER NOT NULL,
                    last_seen TEXT, positive_hash TEXT
                );
                CREATE INDEX IF NOT EXISTS images_date ON images(sort_date DESC, id);
                CREATE INDEX IF NOT EXISTS images_root ON images(root);
                CREATE INDEX IF NOT EXISTS images_folder ON images(folder);
                CREATE INDEX IF NOT EXISTS images_model ON images(model);
                CREATE INDEX IF NOT EXISTS images_workflow ON images(workflow_hash);
                CREATE INDEX IF NOT EXISTS images_config ON images(configuration_hash);
                CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
                    image_id UNINDEXED, filename, positive, negative, model, loras, tags,
                    tokenize='unicode61 remove_diacritics 2'
                );
                CREATE TABLE IF NOT EXISTS library.annotations (
                    path_key TEXT PRIMARY KEY, favorite INTEGER NOT NULL DEFAULT 0, tags TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS library.collections (id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS library.collection_items (
                    collection_id TEXT NOT NULL, path_key TEXT NOT NULL,
                    PRIMARY KEY(collection_id, path_key)
                );
            """)
            columns = {r[1] for r in db.execute("PRAGMA table_info(images)")}
            for name, definition in {
                "media_kind": "TEXT NOT NULL DEFAULT 'image'",
                "duration": "REAL",
                "fps": "REAL",
                "technical": "TEXT NOT NULL DEFAULT '{}'",
                "metadata_fingerprint": "TEXT",
            }.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE images ADD COLUMN {name} {definition}")
            if "models" not in columns:
                db.execute(
                    "ALTER TABLE images ADD COLUMN models TEXT NOT NULL DEFAULT '[]'"
                )
                db.execute("UPDATE images SET version=0")
            if "positive_hash" not in columns:
                db.execute("ALTER TABLE images ADD COLUMN positive_hash TEXT")
            db.execute(
                "UPDATE images SET positive_hash=prompt_hash(positive) WHERE positive_hash IS NULL AND positive<>''"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS images_positive_hash ON images(positive_hash)"
            )
        self.prompts = PromptStore(self, IMAGE_SUMMARY_COLUMNS)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.create_function("prompt_hash", 1, prompt_hash, deterministic=True)
        db.create_function(
            "casefold",
            1,
            lambda value: value.casefold() if isinstance(value, str) else "",
            deterministic=True,
        )
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("ATTACH DATABASE ? AS library", (str(self.user_path),))
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def fingerprint(self, key: str):
        with self.connect() as db:
            row = db.execute(
                "SELECT size,mtime_ns,version,thumbnail,metadata_fingerprint FROM images WHERE path_key=?",
                (key,),
            ).fetchone()
            return dict(row) if row else None

    def seen(self, key: str, token: str):
        with self.write_lock, self.connect() as db:
            db.execute("UPDATE images SET last_seen=? WHERE path_key=?", (token, key))

    @staticmethod
    def _fts(db, image):
        annotation = db.execute(
            "SELECT tags FROM library.annotations WHERE path_key=?",
            (image["path_key"],),
        ).fetchone()
        db.execute("DELETE FROM search WHERE image_id=?", (image["id"],))
        db.execute(
            "INSERT INTO search VALUES (?,?,?,?,?,?,?)",
            (
                image["id"],
                image["filename"],
                "\n\n".join(
                    r[0]
                    for r in db.execute(
                        "SELECT text FROM prompt_entries WHERE image_id=?",
                        (image["id"],),
                    )
                ),
                image["negative"],
                image["models"],
                image["loras"],
                " ".join(json.loads(annotation[0])) if annotation else "",
            ),
        )

    def upsert(self, row: dict):
        row = {**row, "positive_hash": prompt_hash(row["positive"])}
        columns = list(row)
        with self.write_lock, self.connect() as db:
            db.execute(
                f"INSERT INTO images ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) ON CONFLICT(path_key) DO UPDATE SET "
                + ",".join(
                    f"{c}=excluded.{c}" for c in columns if c not in {"id", "path_key"}
                ),
                list(row.values()),
            )
            metadata = json.loads(row["metadata"])
            self.prompts.replace(
                db,
                row["id"],
                metadata.get(
                    "documents",
                    [
                        {
                            "key": "positive",
                            "scope": "positive",
                            "label": "Positive prompt",
                            "text": row["positive"],
                        }
                    ],
                ),
            )
            self._fts(db, row)

    def remove(self, key: str):
        with self.write_lock, self.connect() as db:
            db.execute(
                "DELETE FROM search WHERE image_id IN (SELECT id FROM images WHERE path_key=?)",
                (key,),
            )
            db.execute("DELETE FROM images WHERE path_key=?", (key,))

    def prune(self, root: str, token: str):
        with self.write_lock, self.connect() as db:
            args = (root, token)
            count = db.execute(
                "SELECT count(*) FROM images WHERE root=? AND (last_seen IS NULL OR last_seen != ?)",
                args,
            ).fetchone()[0]
            db.execute(
                "DELETE FROM search WHERE image_id IN (SELECT id FROM images WHERE root=? AND (last_seen IS NULL OR last_seen != ?))",
                args,
            )
            db.execute(
                "DELETE FROM images WHERE root=? AND (last_seen IS NULL OR last_seen != ?)",
                args,
            )
            return count

    def restrict_roots(self, roots: list[str]):
        with self.write_lock, self.connect() as db:
            placeholders = ",".join("?" for _ in roots) or "NULL"
            db.execute(
                f"DELETE FROM search WHERE image_id IN (SELECT id FROM images WHERE root NOT IN ({placeholders}))",
                roots,
            )
            # NOT IN (NULL) is unknown, so explicitly handle an empty configuration.
            db.execute(
                f"DELETE FROM images WHERE root NOT IN ({placeholders})"
                if roots
                else "DELETE FROM images",
                roots,
            )
            if not roots:
                db.execute("DELETE FROM search")

    @staticmethod
    def summary(row):
        item = dict(row)
        item["tags"] = json.loads(item.get("tags") or "[]")
        item["favorite"] = bool(item.get("favorite"))
        item["loras"] = json.loads(item["loras"])
        item["seeds"] = json.loads(item["seeds"])
        if "technical" in item:
            item["technical"] = json.loads(item["technical"])
        return item

    def detail(self, image_id: str):
        with self.connect() as db:
            row = db.execute(
                "SELECT i.*,coalesce(a.favorite,0) favorite,coalesce(a.tags,'[]') tags FROM images i LEFT JOIN library.annotations a USING(path_key) WHERE i.id=?",
                (image_id,),
            ).fetchone()
            if not row:
                return None
            item = self.summary(row)
            item["metadata"] = json.loads(item["metadata"])
            item["prompt_documents"] = self.prompts.documents(image_id)
            item["raw_json"] = json.dumps(
                item["metadata"]["raw"], ensure_ascii=False, indent=2
            )
            item["collections"] = [
                r[0]
                for r in db.execute(
                    "SELECT collection_id FROM library.collection_items WHERE path_key=?",
                    (item["path_key"],),
                )
            ]
            return item

    def file(self, image_id: str):
        """Media requests do not deserialize the metadata blob."""
        with self.connect() as db:
            row = db.execute(
                "SELECT id,path,filename,thumbnail,media_kind,duration,fps,technical,size,mtime_ns FROM images WHERE id=?",
                (image_id,),
            ).fetchone()
            return dict(row) if row else None

    def prompt_text(self, image_id: str):
        """Fetch a full prompt without loading its workflow or raw metadata."""
        with self.connect() as db:
            row = db.execute(
                "SELECT id,path,positive_hash,positive FROM images WHERE id=?",
                (image_id,),
            ).fetchone()
            return dict(row) if row else None

    def embedding_prompts(self, roots: list[str]):
        return self.prompts.embeddings(roots)

    def similar_prompts(self, image_id, roots, **kwargs):
        return self.prompts.similar(
            self.prompts.text(image_id=image_id), roots, **kwargs
        )

    def images(
        self,
        *,
        q="",
        exact=False,
        root="",
        folder="",
        model="",
        lora="",
        seed="",
        tag="",
        favorite=False,
        collection="",
        after=None,
        before=None,
        sort="date",
        direction="desc",
        group="",
        offset=0,
        limit=60,
        workflow="",
        configuration="",
        prompt="",
        unique_prompts=False,
        media_kind="",
        prompt_scope="",
    ):
        where, args = [], []
        if q.strip() and not unique_prompts:
            if exact:
                where.append(
                    "instr(casefold(i.filename || ' ' || i.positive || ' ' || i.negative || ' ' || i.models || ' ' || i.loras || ' ' || coalesce(a.tags,'') || ' ' || coalesce((SELECT group_concat(ep.text,' ') FROM prompt_entries ep WHERE ep.image_id=i.id),'')),casefold(?))>0"
                )
                args.append(q.strip())
            else:
                terms = re.findall(r"[^\W_]+", q, flags=re.UNICODE)
                if terms:
                    where.append(
                        "i.id IN (SELECT image_id FROM search WHERE search MATCH ?)"
                    )
                    args.append(
                        " AND ".join(
                            '"' + t.replace('"', '""') + '"' for t in terms[:40]
                        )
                    )
                else:
                    where.append("0")
        for col, value in (
            ("root", root),
            ("workflow_hash", workflow),
            ("configuration_hash", configuration),
        ):
            if value:
                where.append(f"i.{col}=?")
                args.append(value)
        if model:
            where.append("EXISTS (SELECT 1 FROM json_each(i.models) WHERE value=?)")
            args.append(model)
        if folder:
            # A separator boundary avoids matching 'cat' against 'catalog'. No LIKE wildcard expansion.
            where.append("(i.folder=? OR substr(i.folder,1,length(?)+1)=? || ?)")
            args.extend([folder, folder, folder, str(Path("a") / "b")[1]])
        for col, value in (("loras", lora), ("seeds", seed)):
            if value:
                where.append(
                    f"EXISTS (SELECT 1 FROM json_each(i.{col}) WHERE CAST(value AS TEXT)=?)"
                )
                args.append(value)
        if tag:
            where.append(
                "EXISTS (SELECT 1 FROM json_each(coalesce(a.tags,'[]')) WHERE value=?)"
            )
            args.append(tag)
        if favorite:
            where.append("a.favorite=1")
        if collection:
            where.append(
                "EXISTS (SELECT 1 FROM library.collection_items c WHERE c.path_key=i.path_key AND c.collection_id=?)"
            )
            args.append(collection)
        if after is not None:
            where.append("i.sort_date>=?")
            args.append(after)
        if before is not None:
            where.append("i.sort_date<?")
            args.append(before)
        if prompt:
            where.append(
                "EXISTS (SELECT 1 FROM prompt_entries ep WHERE ep.image_id=i.id AND ep.group_hash=?)"
            )
            args.append(prompt)
        if media_kind:
            where.append("i.media_kind=?")
            args.append(media_kind)
        if prompt_scope and not unique_prompts:
            document_conditions = ["ep.image_id=i.id", "ep.scope=?"]
            args.append(prompt_scope)
            if q.strip():
                terms = [q.strip()] if exact else re.findall(r"[^\W_]+", q)[:40]
                for term in terms:
                    document_conditions.append("instr(casefold(ep.text),casefold(?))>0")
                    args.append(term)
            where.append(
                "EXISTS (SELECT 1 FROM prompt_entries ep WHERE "
                + " AND ".join(document_conditions)
                + ")"
            )
        orders = {
            "date": "i.sort_date",
            "filename": "i.filename COLLATE NOCASE",
            "resolution": "i.width*i.height",
            "model": "coalesce(i.model,'') COLLATE NOCASE",
        }
        grouping = {
            "model": "coalesce(i.model,'')",
            "date": "date(i.sort_date,'unixepoch','localtime')",
            "workflow": "coalesce(i.workflow_hash,'')",
        }
        order = (
            (grouping[group] + "," if group in grouping else "")
            + orders.get(sort, orders["date"])
            + (" ASC" if direction == "asc" else " DESC")
            + ",i.id"
        )
        if unique_prompts:
            return self.prompts.list(
                where,
                args,
                q=q,
                exact=exact,
                scope=prompt_scope,
                order=order,
                offset=offset,
                limit=limit,
            )
        joins = " FROM images i LEFT JOIN library.annotations a USING(path_key)"
        clause = " WHERE " + " AND ".join(where) if where else ""
        with self.connect() as db:
            counts = db.execute(
                "SELECT count(*),count(DISTINCT i.positive_hash)" + joins + clause, args
            ).fetchone()
            total = counts[1] if unique_prompts else counts[0]
            summary_columns = IMAGE_SUMMARY_COLUMNS
            rows = db.execute(
                "SELECT "
                + summary_columns
                + joins
                + clause
                + f" ORDER BY {order} LIMIT ? OFFSET ?",
                args + [limit, offset],
            ).fetchall()
            return {
                "items": [self.summary(row) for row in rows],
                "total": total,
                "image_total": counts[0],
                "offset": offset,
                "limit": limit,
            }

    def annotate(
        self, image_ids: list[str], favorite: bool | None, tags: list[str] | None
    ):
        with self.write_lock, self.connect() as db:
            for image_id in image_ids:
                image = db.execute(
                    "SELECT * FROM images WHERE id=?", (image_id,)
                ).fetchone()
                if not image:
                    continue
                db.execute(
                    "INSERT OR IGNORE INTO library.annotations(path_key) VALUES (?)",
                    (image["path_key"],),
                )
                if favorite is not None:
                    db.execute(
                        "UPDATE library.annotations SET favorite=? WHERE path_key=?",
                        (int(favorite), image["path_key"]),
                    )
                if tags is not None:
                    db.execute(
                        "UPDATE library.annotations SET tags=? WHERE path_key=?",
                        (json.dumps(tags), image["path_key"]),
                    )
                self._fts(db, image)

    def facets(self):
        with self.connect() as db:

            def pairs(sql):
                return [{"name": row[0], "count": row[1]} for row in db.execute(sql)]

            return {
                "total": db.execute("SELECT count(*) FROM images").fetchone()[0],
                "unique_prompts": db.execute(
                    "SELECT count(DISTINCT group_hash) FROM prompt_entries"
                ).fetchone()[0],
                "favorites": db.execute(
                    "SELECT count(*) FROM images JOIN library.annotations USING(path_key) WHERE favorite=1"
                ).fetchone()[0],
                "models": pairs(
                    "SELECT j.value,count(DISTINCT i.id) FROM images i,json_each(i.models) j GROUP BY j.value ORDER BY j.value"
                ),
                "loras": pairs(
                    "SELECT j.value,count(DISTINCT i.id) FROM images i,json_each(i.loras) j GROUP BY j.value ORDER BY j.value"
                ),
                "folders": pairs(
                    "SELECT folder,count(*) FROM images GROUP BY folder ORDER BY folder"
                ),
                "roots": pairs(
                    "SELECT root,count(*) FROM images GROUP BY root ORDER BY root"
                ),
                "tags": pairs(
                    "SELECT j.value,count(*) FROM images i JOIN library.annotations a USING(path_key),json_each(a.tags) j GROUP BY j.value ORDER BY j.value"
                ),
                "collections": [
                    dict(row)
                    for row in db.execute(
                        "SELECT c.id,c.name,count(i.id) count FROM library.collections c LEFT JOIN library.collection_items ci ON c.id=ci.collection_id LEFT JOIN images i ON i.path_key=ci.path_key GROUP BY c.id ORDER BY c.name"
                    )
                ],
            }

    def create_collection(self, name: str):
        item = {"id": uuid.uuid4().hex, "name": name}
        with self.write_lock, self.connect() as db:
            db.execute(
                "INSERT INTO library.collections VALUES (?,?)",
                (item["id"], item["name"]),
            )
        return item

    def collection_items(self, collection_id: str, ids: list[str], remove=False):
        with self.write_lock, self.connect() as db:
            if not db.execute(
                "SELECT 1 FROM library.collections WHERE id=?", (collection_id,)
            ).fetchone():
                raise ValueError("Collection not found")
            for image_id in ids:
                row = db.execute(
                    "SELECT path_key FROM images WHERE id=?", (image_id,)
                ).fetchone()
                if row:
                    if remove:
                        db.execute(
                            "DELETE FROM library.collection_items WHERE collection_id=? AND path_key=?",
                            (collection_id, row[0]),
                        )
                    else:
                        db.execute(
                            "INSERT OR IGNORE INTO library.collection_items VALUES (?,?)",
                            (collection_id, row[0]),
                        )

    def delete_collection(self, collection_id: str):
        with self.write_lock, self.connect() as db:
            db.execute(
                "DELETE FROM library.collection_items WHERE collection_id=?",
                (collection_id,),
            )
            db.execute("DELETE FROM library.collections WHERE id=?", (collection_id,))

    def rebuild(self):
        with self.write_lock, self.connect() as db:
            db.execute("DELETE FROM images")
            db.execute("DELETE FROM search")
