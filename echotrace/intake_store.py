"""分批收档的 SQLite 持久化与原子封存。

登记、片段回执、隔离与确认都落库，使资料员离开页面、工作台重启后仍可
查回收档进度；确认与成果封存放在同一事务里，杜绝半成功。
"""
from contextlib import closing
import sqlite3
import time

from .contract import ContractError, canonical, decode
from . import intake


class IntakeStore:
    def __init__(self, connect):
        self._connect = connect
        with closing(self._connect()) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA busy_timeout=4000')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS intake_registrations(
                    intake_id TEXT PRIMARY KEY,
                    cable TEXT NOT NULL,
                    registration BLOB NOT NULL,
                    created_ns INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS intake_receipts(
                    receipt_id TEXT PRIMARY KEY,
                    intake_id TEXT NOT NULL,
                    side TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    recv_order INTEGER NOT NULL,
                    origin TEXT NOT NULL,
                    fragment_digest TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT,
                    payload BLOB NOT NULL,
                    UNIQUE(intake_id, recv_order));
                CREATE TABLE IF NOT EXISTS intake_confirmations(
                    confirm_id TEXT PRIMARY KEY,
                    intake_id TEXT NOT NULL,
                    basis TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    used_receipts BLOB NOT NULL,
                    created_ns INTEGER NOT NULL);
            ''')

    def _now(self):
        return time.time_ns()

    def load_registration(self, db, intake_id):
        row = db.execute('SELECT registration FROM intake_registrations WHERE intake_id=?',
                         (intake_id,)).fetchone()
        if row is None:
            raise ContractError('没有这个收档批次', 404)
        return decode(row[0])

    def get_registration(self, intake_id):
        with closing(self._connect()) as db:
            return self.load_registration(db, intake_id)

    def register(self, registration):
        intake_id = intake.registration_id(registration)
        with closing(self._connect()) as db, db:
            existed = db.execute('SELECT 1 FROM intake_registrations WHERE intake_id=?',
                                 (intake_id,)).fetchone() is not None
            if not existed:
                db.execute('INSERT INTO intake_registrations'
                           '(intake_id, cable, registration, created_ns) VALUES(?,?,?,?)',
                           (intake_id, registration['cable'], canonical(registration), self._now()))
            receipts = self._receipts(db, intake_id)
            current = intake.snapshot(registration, receipts)
        return intake_id, current, existed

    def _receipts(self, db, intake_id):
        rows = db.execute('SELECT payload FROM intake_receipts WHERE intake_id=? ORDER BY recv_order',
                          (intake_id,)).fetchall()
        return [decode(row[0]) for row in rows]

    def snapshot(self, intake_id):
        with closing(self._connect()) as db:
            registration = self.load_registration(db, intake_id)
            return intake.snapshot(registration, self._receipts(db, intake_id))

    def list_intakes(self):
        with closing(self._connect()) as db:
            rows = db.execute('SELECT intake_id, cable, created_ns FROM intake_registrations'
                              ' ORDER BY created_ns DESC, intake_id LIMIT 100').fetchall()
        return [dict(intake=key, cable=cable, created_ns=created) for key, cable, created in rows]

    def add_receipt(self, fragment, receipt_id, fragment_digest):
        intake_id = fragment['intake']
        # BEGIN IMMEDIATE 立即取写锁，串行化同批次的 recv_order 分配，避免并发片段
        # 抢到相同序号；遇到锁竞争时有限重试。
        for attempt in range(20):
            try:
                with closing(self._connect()) as db, db:
                    db.execute('BEGIN IMMEDIATE')
                    registration = self.load_registration(db, intake_id)
                    existing = db.execute('SELECT payload FROM intake_receipts WHERE receipt_id=?',
                                          (receipt_id,)).fetchone()
                    if existing is not None:
                        duplicate = decode(existing[0])
                        current = intake.snapshot(registration, self._receipts(db, intake_id))
                        return current, duplicate, True
                    order_row = db.execute('SELECT COALESCE(MAX(recv_order)+1,0) FROM intake_receipts'
                                           ' WHERE intake_id=?', (intake_id,)).fetchone()
                    receipt = dict(receipt=receipt_id, intake=intake_id, side=fragment['side'],
                                   sequence=fragment['sequence'], recv_order=order_row[0],
                                   origin=fragment['source']['origin'], fragment_digest=fragment_digest,
                                   status=intake.RECEIVED, samples=fragment['samples'],
                                   created_ns=self._now())
                    db.execute('INSERT INTO intake_receipts'
                               '(receipt_id, intake_id, side, sequence, recv_order, origin,'
                               ' fragment_digest, status, payload) VALUES(?,?,?,?,?,?,?,?,?)',
                               (receipt_id, intake_id, receipt['side'], receipt['sequence'],
                                receipt['recv_order'], receipt['origin'], fragment_digest,
                                receipt['status'], canonical(receipt)))
                    current = intake.snapshot(registration, self._receipts(db, intake_id))
                return current, receipt, False
            except sqlite3.OperationalError as exc:
                if 'locked' not in str(exc).lower() or attempt == 19:
                    raise
                time.sleep(0.02 * (attempt + 1))
        raise ContractError('成果库繁忙，请重试', 503)

    def quarantine(self, intake_id, receipt_id, reason):
        with closing(self._connect()) as db, db:
            registration = self.load_registration(db, intake_id)
            row = db.execute('SELECT status FROM intake_receipts WHERE receipt_id=? AND intake_id=?',
                             (receipt_id, intake_id)).fetchone()
            if row is None:
                raise ContractError('没有这张片段回执', 404)
            already = row[0] == intake.QUARANTINED
            if not already:
                payload = decode(db.execute('SELECT payload FROM intake_receipts WHERE receipt_id=?',
                                            (receipt_id,)).fetchone()[0])
                payload['status'] = intake.QUARANTINED
                payload['reason'] = reason
                db.execute('UPDATE intake_receipts SET status=?, reason=?, payload=? WHERE receipt_id=?',
                           (intake.QUARANTINED, reason, canonical(payload), receipt_id))
            current = intake.snapshot(registration, self._receipts(db, intake_id))
        return current, already

    @staticmethod
    def _find_confirmation(db, confirm_id):
        row = db.execute('SELECT intake_id, basis, digest, sequence, used_receipts, created_ns'
                         ' FROM intake_confirmations WHERE confirm_id=?',
                         (confirm_id,)).fetchone()
        if row is None:
            return None
        intake_id, basis, key, sequence, used, created_ns = row
        return dict(confirm=confirm_id, intake=intake_id, basis=basis, digest=key,
                    sequence=sequence, used_receipts=decode(used), created_ns=created_ns)

    def find_confirmation(self, confirm_id):
        with closing(self._connect()) as db:
            return self._find_confirmation(db, confirm_id)

    def confirm(self, confirm_id, intake_id, basis, build_packet):
        """同事务核对基准、拼装校验并写成果与确认记录。

        build_packet 在写事务内回调，返回 (packet, used_receipts, snapshot)，
        确保确认期间到达的新片段不可能被一并封存。同一确认标识重试得到同成果。
        """
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            registration = self.load_registration(db, intake_id)
            prior = self._find_confirmation(db, confirm_id)
            if prior is not None:
                if prior['intake'] != intake_id:
                    raise ContractError('确认标识已用于另一收档批次', 409)
                prior['duplicate'] = True
                prior['created_packet'] = False
                return prior, False
            receipts = self._receipts(db, intake_id)
            current = intake.snapshot(registration, receipts)
            if current['basis'] != basis:
                raise ContractError('材料清单在核对后发生变化，请按最新回执重新确认', 409,
                                    dict(snapshot=current))
            packet, used_receipts, assembled_snapshot = build_packet(registration, receipts)
            result = db.execute('INSERT OR IGNORE INTO packets(digest, subject, payload) VALUES(?,?,?)',
                                (packet['digest'], packet['subject'], canonical(packet)))
            record = db.execute('SELECT seq FROM packets WHERE digest=?',
                                (packet['digest'],)).fetchone()
            db.execute('INSERT INTO intake_confirmations'
                       '(confirm_id, intake_id, basis, digest, sequence, used_receipts, created_ns)'
                       ' VALUES(?,?,?,?,?,?,?)',
                       (confirm_id, intake_id, basis, packet['digest'], record[0],
                        canonical(used_receipts), self._now()))
            confirmation = dict(confirm=confirm_id, intake=intake_id, basis=basis,
                                digest=packet['digest'], sequence=record[0],
                                used_receipts=used_receipts, created_ns=self._now(),
                                created_packet=result.rowcount == 1,
                                created_confirmation=True)
        return confirmation, True
