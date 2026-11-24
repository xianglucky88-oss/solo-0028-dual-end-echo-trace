from contextlib import closing
import sqlite3
from pathlib import Path

from .artifacts import verify_packet
from .contract import ContractError, canonical, decode
from .inventory import NUMBER_PREFIX


class Archive:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('''CREATE TABLE IF NOT EXISTS packets(
                seq INTEGER PRIMARY KEY, digest TEXT UNIQUE NOT NULL,
                subject TEXT NOT NULL, payload BLOB NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS inventory_sheets(
                sheet_no TEXT PRIMARY KEY, payload BLOB NOT NULL,
                cutoff_sequence INTEGER NOT NULL, issued_at TEXT NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS idx_packets_subject_seq ON packets(subject, seq)')

    def connect(self):
        return sqlite3.connect(self.path, timeout=4)

    def seal(self, packet):
        with closing(self.connect()) as db, db:
            result = db.execute('INSERT OR IGNORE INTO packets(digest, subject, payload) VALUES(?,?,?)',
                                (packet['digest'], packet['subject'], canonical(packet)))
            record = db.execute('SELECT seq FROM packets WHERE digest=?', (packet['digest'],)).fetchone()
        return dict(digest=packet['digest'], sequence=record[0], created=result.rowcount == 1)

    def list(self):
        with closing(self.connect()) as db:
            rows = db.execute('SELECT seq, digest, subject FROM packets ORDER BY seq DESC LIMIT 100').fetchall()
        return [dict(sequence=seq, digest=key, subject=subject) for seq, key, subject in rows]

    def head_sequence(self):
        with closing(self.connect()) as db:
            row = db.execute('SELECT MAX(seq) FROM packets').fetchone()
        return row[0]

    def latest_at_cutoff(self, subjects, cutoff):
        """每个对象在截至点（含）之前序号最大的封存行；与版本菜单无关。"""
        if not subjects:
            return {}
        placeholders = ','.join('?' for _ in subjects)
        sql = f'''SELECT p.seq, p.digest, p.subject FROM packets p
                  JOIN (SELECT subject, MAX(seq) AS seq FROM packets
                        WHERE seq <= ? AND subject IN ({placeholders}) GROUP BY subject) m
                  ON m.subject = p.subject AND m.seq = p.seq'''
        with closing(self.connect()) as db:
            rows = db.execute(sql, (cutoff, *subjects)).fetchall()
        return {subject: dict(sequence=seq, digest=key, subject=subject)
                for seq, key, subject in rows}

    def read_raw(self, key):
        with closing(self.connect()) as db:
            row = db.execute('SELECT payload FROM packets WHERE digest=?', (key,)).fetchone()
        if row is None:
            raise ContractError('没有这个成果版本', 404)
        return row[0]

    def read(self, key):
        packet = verify_packet(decode(self.read_raw(key)))
        if packet['digest'] != key:
            raise ContractError('成果版本与封存索引不一致', 409)
        return packet

    def issue_sheet(self, sheet, issued_at):
        with closing(self.connect()) as db, db:
            number = db.execute('SELECT COUNT(*) FROM inventory_sheets').fetchone()[0] + 1
            sheet_no = f'{NUMBER_PREFIX}-{number:04d}'
            if sheet['sheet'] != sheet_no:
                raise ContractError('盘点单号与登记册序号不一致', 409)
            db.execute('INSERT INTO inventory_sheets(sheet_no, payload, cutoff_sequence, issued_at) VALUES(?,?,?,?)',
                       (sheet_no, canonical(sheet), sheet['cutoff_sequence'], issued_at))
        return sheet_no

    def sheet_count(self):
        with closing(self.connect()) as db:
            return db.execute('SELECT COUNT(*) FROM inventory_sheets').fetchone()[0]

    def list_sheets(self):
        with closing(self.connect()) as db:
            rows = db.execute('''SELECT sheet_no, cutoff_sequence, issued_at
                                 FROM inventory_sheets ORDER BY sheet_no''').fetchall()
        return [dict(sheet=no, cutoff_sequence=cutoff, issued_at=at) for no, cutoff, at in rows]

    def read_sheet(self, sheet_no):
        with closing(self.connect()) as db:
            row = db.execute('SELECT payload FROM inventory_sheets WHERE sheet_no=?', (sheet_no,)).fetchone()
        if row is None:
            raise ContractError('没有这张盘点单', 404)
        return decode(row[0])
