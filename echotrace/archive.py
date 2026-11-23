from contextlib import closing
import sqlite3
from pathlib import Path

from .artifacts import digest, verify_packet
from .contract import canonical, decode, ContractError


class Archive:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('''CREATE TABLE IF NOT EXISTS packets(
                seq INTEGER PRIMARY KEY, digest TEXT UNIQUE NOT NULL,
                subject TEXT NOT NULL, payload BLOB NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS errata(
                seq INTEGER PRIMARY KEY, number TEXT UNIQUE NOT NULL,
                digest TEXT NOT NULL, payload BLOB NOT NULL)''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=4)

    def seal(self, packet):
        with closing(self.connect()) as db, db:
            result = db.execute('INSERT OR IGNORE INTO packets(digest, subject, payload) VALUES(?,?,?)',
                                (packet['digest'], packet['subject'], canonical(packet)))
            record = db.execute('SELECT seq FROM packets WHERE digest=?', (packet['digest'],)).fetchone()
        return dict(digest=packet['digest'], sequence=record[0], created=result.rowcount == 1)

    def seal_errata(self, number, sheet):
        payload = canonical(sheet)
        key = digest(sheet)
        with closing(self.connect()) as db, db:
            result = db.execute('INSERT OR IGNORE INTO errata(number, digest, payload) VALUES(?,?,?)',
                                (number, key, payload))
            record = db.execute('SELECT seq, digest FROM errata WHERE number=?', (number,)).fetchone()
        if record[1] != key:
            raise ContractError('同编号勘误单内容不一致，不能覆盖已签发记录', 409)
        return dict(digest=key, sequence=record[0], created=result.rowcount == 1)

    def read_errata(self, number):
        with closing(self.connect()) as db:
            row = db.execute('SELECT payload FROM errata WHERE number=?', (number,)).fetchone()
        if row is None:
            raise ContractError('没有这份勘误单', 404)
        return decode(row[0])

    def list_errata(self):
        with closing(self.connect()) as db:
            rows = db.execute('SELECT seq, number, digest FROM errata ORDER BY seq DESC LIMIT 100').fetchall()
        return [dict(sequence=seq, number=number, digest=key) for seq, number, key in rows]

    def list(self):
        with closing(self.connect()) as db:
            rows = db.execute('SELECT seq, digest, subject FROM packets ORDER BY seq DESC LIMIT 100').fetchall()
        return [dict(sequence=seq, digest=key, subject=subject) for seq, key, subject in rows]

    def read(self, key):
        with closing(self.connect()) as db:
            row = db.execute('SELECT payload FROM packets WHERE digest=?', (key,)).fetchone()
        if row is None:
            raise ContractError('没有这个成果版本', 404)
        packet = verify_packet(decode(row[0]))
        if packet['digest'] != key:
            raise ContractError('成果版本与封存索引不一致', 409)
        return packet
