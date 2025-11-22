import sqlite3
import time
from typing import List, Optional, Dict, Any

class Database:
    def __init__(self, path: str = "smartnotes.db"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        cur = self.conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON;")
        
        cur.execute("""
        CREATE TABLE IF NOT EXISTS folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_id INTEGER NULL REFERENCES folders(id) ON DELETE SET NULL,
            title TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS note_tags (
            note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
            PRIMARY KEY (note_id, tag_id)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """)
        
        cur.execute("CREATE INDEX IF NOT EXISTS idx_notes_folder ON notes(folder_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_notes_title ON notes(title)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(updated_at DESC)")

        cur.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
            title, 
            content, 
            content='notes', 
            content_rowid='id'
        );
        """)

        cur.execute("""
        CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
            INSERT INTO notes_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
        END;
        """)
        cur.execute("""
        CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
            INSERT INTO notes_fts(notes_fts, rowid, title, content) VALUES('delete', old.id, old.title, old.content);
        END;
        """)
        cur.execute("""
        CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
            INSERT INTO notes_fts(notes_fts, rowid, title, content) VALUES('delete', old.id, old.title, old.content);
            INSERT INTO notes_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
        END;
        """)

        self.conn.commit()
        
        cur.execute("SELECT count(*) as c FROM notes")
        c_notes = cur.fetchone()["c"]
        if c_notes > 0:
            cur.execute("SELECT count(*) as c FROM notes_fts")
            c_fts = cur.fetchone()["c"]
            if c_fts == 0:
                cur.execute("INSERT INTO notes_fts(notes_fts) VALUES('rebuild')")
                self.conn.commit()

    def get_setting(self, key: str) -> Optional[str]:
        cur = self.conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str):
        cur = self.conn.cursor()
        cur.execute("""
        INSERT INTO settings(key, value) VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (key, value))
        self.conn.commit()

    def list_folders(self) -> List[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute("SELECT id, name FROM folders ORDER BY name COLLATE NOCASE")
        return cur.fetchall()

    def create_folder(self, name: str) -> int:
        cur = self.conn.cursor()
        cur.execute("INSERT INTO folders(name) VALUES(?)", (name,))
        self.conn.commit()
        return cur.lastrowid

    def rename_folder(self, folder_id: int, name: str):
        cur = self.conn.cursor()
        cur.execute("UPDATE folders SET name=? WHERE id=?", (name, folder_id))
        self.conn.commit()

    def delete_folder(self, folder_id: int):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM folders WHERE id=?", (folder_id,))
        self.conn.commit()

    def create_note(self, folder_id: Optional[int], title: str = "") -> int:
        now = int(time.time())
        cur = self.conn.cursor()
        cur.execute("""
        INSERT INTO notes(folder_id, title, content, created_at, updated_at)
        VALUES(?, ?, '', ?, ?)
        """, (folder_id, title, now, now))
        self.conn.commit()
        return cur.lastrowid

    def update_note(self, note_id: int, title: str, content: str, folder_id: Optional[int]):
        now = int(time.time())
        cur = self.conn.cursor()
        cur.execute("""
        UPDATE notes SET title=?, content=?, folder_id=?, updated_at=?
        WHERE id=?
        """, (title, content, folder_id, now, note_id))
        self.conn.commit()

    def delete_note(self, note_id: int):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM notes WHERE id=?", (note_id,))
        self.conn.commit()

    def get_note(self, note_id: int) -> Optional[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute("""
        SELECT id, folder_id, title, content, created_at, updated_at
        FROM notes WHERE id=?
        """, (note_id,))
        return cur.fetchone()

    def get_note_id_by_title(self, title: str) -> Optional[int]:
        cur = self.conn.cursor()
        cur.execute("SELECT id FROM notes WHERE title = ? COLLATE NOCASE LIMIT 1", (title.strip(),))
        row = cur.fetchone()
        return row["id"] if row else None

    def list_note_tags(self, note_id: int) -> List[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute("""
        SELECT t.id, t.name
        FROM tags t
        JOIN note_tags nt ON nt.tag_id = t.id
        WHERE nt.note_id=?
        ORDER BY t.name COLLATE NOCASE
        """, (note_id,))
        return cur.fetchall()

    def set_note_tags(self, note_id: int, tag_names: List[str]):
        tag_names = [n.strip() for n in tag_names if n.strip()]
        cur = self.conn.cursor()
        tag_ids = []
        for name in tag_names:
            try:
                cur.execute("INSERT INTO tags(name) VALUES(?)", (name,))
                tag_ids.append(cur.lastrowid)
            except sqlite3.IntegrityError:
                cur.execute("SELECT id FROM tags WHERE name=?", (name,))
                row = cur.fetchone()
                if row:
                    tag_ids.append(row["id"])
        cur.execute("DELETE FROM note_tags WHERE note_id=?", (note_id,))
        for tid in tag_ids:
            cur.execute("INSERT OR IGNORE INTO note_tags(note_id, tag_id) VALUES(?, ?)", (note_id, tid))
        self.conn.commit()
        self.clean_unused_tags()

    def all_tags(self) -> List[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute("""
        SELECT t.id, t.name, COALESCE(COUNT(nt.note_id), 0) AS usage_count
        FROM tags t
        LEFT JOIN note_tags nt ON nt.tag_id = t.id
        GROUP BY t.id, t.name
        ORDER BY t.name COLLATE NOCASE
        """)
        return cur.fetchall()

    def clean_unused_tags(self):
        cur = self.conn.cursor()
        cur.execute("""
        DELETE FROM tags
        WHERE id NOT IN (SELECT tag_id FROM note_tags)
        """)
        self.conn.commit()

    def search_notes(
        self,
        folder_id: Optional[int],
        query: str,
        tag_ids: List[int],
    ) -> List[Dict[str, Any]]:
        params: List[Any] = []
        where = []

        if folder_id is not None:
            where.append("n.folder_id = ?")
            params.append(folder_id)

        if query:
            clean_q = query.replace('"', '""')
            if " " in clean_q:
                fts_query = f'"{clean_q}"'
            else:
                fts_query = f'"{clean_q}"*'
            
            where.append("n.id IN (SELECT rowid FROM notes_fts WHERE notes_fts MATCH ?)")
            params.append(fts_query)

        if tag_ids:
            placeholders = ",".join(["?"] * len(tag_ids))
            subq = f"""
                SELECT nt.note_id
                FROM note_tags nt
                WHERE nt.tag_id IN ({placeholders})
                GROUP BY nt.note_id
                HAVING COUNT(DISTINCT nt.tag_id) = {len(tag_ids)}
            """
            where.append(f"n.id IN ({subq})")
            params.extend(tag_ids)

        where_sql = "WHERE " + " AND ".join(where) if where else ""
        order_by = "ORDER BY n.updated_at DESC"

        sql = f"""
        SELECT n.id, n.title, n.content, n.folder_id, n.updated_at
        FROM notes n
        {where_sql}
        {order_by}
        LIMIT 1000
        """

        cur = self.conn.cursor()
        try:
            cur.execute(sql, params)
        except sqlite3.OperationalError:
            return []

        rows = cur.fetchall()

        result = []
        for r in rows:
            cur.execute("""
            SELECT t.id, t.name
            FROM tags t
            JOIN note_tags nt ON nt.tag_id = t.id
            WHERE nt.note_id=?
            ORDER BY t.name COLLATE NOCASE
            """, (r["id"],))
            tags = [dict(id=x["id"], name=x["name"]) for x in cur.fetchall()]
            result.append(dict(
                id=r["id"],
                title=r["title"],
                content=r["content"],
                folder_id=r["folder_id"],
                updated_at=r["updated_at"],
                tags=tags
            ))
        return result

    def move_note(self, note_id: int, to_folder_id: Optional[int]):
        cur = self.conn.cursor()
        cur.execute("UPDATE notes SET folder_id=?, updated_at=? WHERE id=?",
                    (to_folder_id, int(time.time()), note_id))
        self.conn.commit()

    def counts(self) -> Dict[str, int]:
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM notes")
        notes = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) AS c FROM folders")
        folders = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) AS c FROM tags")
        tags = cur.fetchone()["c"]
        return {"notes": notes, "folders": folders, "tags": tags}