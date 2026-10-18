"""SQLite storage: scan history + Scam IQ progress.

No accounts, no email, no login. Everything is keyed by an anonymous device id
that the browser generates locally (crypto.randomUUID) and can wipe at any time
via "Delete all my data" in the History tab.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id            TEXT PRIMARY KEY,
    device_id     TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    verdict       TEXT NOT NULL,
    risk_score    INTEGER NOT NULL,
    scam_type     TEXT,
    language      TEXT,
    input_kind    TEXT,
    preview       TEXT,
    result_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_analyses_device ON analyses(device_id, created_at DESC);

CREATE TABLE IF NOT EXISTS scam_iq (
    device_id         TEXT PRIMARY KEY,
    score             INTEGER NOT NULL DEFAULT 0,
    streak_days       INTEGER NOT NULL DEFAULT 0,
    last_active_date  TEXT,
    lessons_completed INTEGER NOT NULL DEFAULT 0,
    quizzes_passed    INTEGER NOT NULL DEFAULT 0,
    correct_answers   INTEGER NOT NULL DEFAULT 0,
    total_answers     INTEGER NOT NULL DEFAULT 0,
    badges            TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS lesson_progress (
    device_id     TEXT NOT NULL,
    pattern_id    TEXT NOT NULL,
    completed_at  TEXT NOT NULL,
    quiz_correct  INTEGER NOT NULL DEFAULT 0,
    quiz_total    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (device_id, pattern_id)
);
"""


class Database:
    def __init__(self, path: str) -> None:
        self.path = str(path)
        parent = Path(self.path).parent
        if str(parent) and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def execute(self, sql: str, params: tuple = ()) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(sql, params)

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock, self._connect() as conn:
            return list(conn.execute(sql, params).fetchall())

    # ------------------------------------------------------------------ scans
    def save_analysis(self, result: dict[str, Any], device_id: str, preview: str) -> None:
        self.execute(
            "INSERT OR REPLACE INTO analyses (id, device_id, created_at, verdict, risk_score, scam_type,"
            " language, input_kind, preview, result_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                result.get("analysis_id"), device_id, result.get("created_at") or datetime.now(timezone.utc).isoformat(),
                str(result.get("verdict")), int(result.get("risk_score", 0)),
                result.get("scam_type"), result.get("language"), str(result.get("input_kind")),
                preview[:160], json.dumps(result, ensure_ascii=False),
            ),
        )

    def list_analyses(self, device_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        rows = self.query(
            "SELECT id, created_at, verdict, risk_score, scam_type, language, input_kind, preview"
            " FROM analyses WHERE device_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (device_id, limit, offset),
        )
        return [dict(r) for r in rows]

    def get_analysis(self, device_id: str, analysis_id: str) -> dict[str, Any] | None:
        rows = self.query(
            "SELECT result_json FROM analyses WHERE device_id = ? AND id = ?", (device_id, analysis_id)
        )
        if not rows:
            return None
        return json.loads(rows[0]["result_json"])

    def count_analyses(self, device_id: str) -> int:
        rows = self.query("SELECT COUNT(*) AS n FROM analyses WHERE device_id = ?", (device_id,))
        return int(rows[0]["n"]) if rows else 0

    def delete_device_data(self, device_id: str) -> dict[str, int]:
        counts = {
            "analyses": self.count_analyses(device_id),
            "lessons": len(self.query("SELECT 1 FROM lesson_progress WHERE device_id = ?", (device_id,))),
        }
        self.execute("DELETE FROM analyses WHERE device_id = ?", (device_id,))
        self.execute("DELETE FROM lesson_progress WHERE device_id = ?", (device_id,))
        self.execute("DELETE FROM scam_iq WHERE device_id = ?", (device_id,))
        return counts

    # -------------------------------------------------------------- community
    def community_stats(self, device_id: str) -> dict[str, Any]:
        """Anonymised, device-local statistics shown on the Home tab.

        Deliberately scoped to this device so the app needs no accounts and no
        central profiling (privacy-first). Aggregation across devices is a
        documented future step, not a claim made today.
        """
        rows = self.query(
            "SELECT verdict, COUNT(*) n FROM analyses WHERE device_id = ? GROUP BY verdict", (device_id,)
        )
        by_verdict = {r["verdict"]: r["n"] for r in rows}
        types = self.query(
            "SELECT scam_type, COUNT(*) n FROM analyses WHERE device_id = ? AND scam_type IS NOT NULL"
            " AND scam_type NOT IN ('legitimate','unknown') GROUP BY scam_type ORDER BY n DESC LIMIT 6",
            (device_id,),
        )
        langs = self.query(
            "SELECT language, COUNT(*) n FROM analyses WHERE device_id = ? GROUP BY language ORDER BY n DESC",
            (device_id,),
        )
        week = self.query(
            "SELECT substr(created_at,1,10) d, COUNT(*) n FROM analyses WHERE device_id = ?"
            " GROUP BY d ORDER BY d DESC LIMIT 7",
            (device_id,),
        )
        return {
            "total_scans": sum(by_verdict.values()),
            "scam_count": by_verdict.get("SCAM", 0),
            "suspicious_count": by_verdict.get("SUSPICIOUS", 0),
            "safe_count": by_verdict.get("SAFE", 0),
            "by_type": [{"scam_type": r["scam_type"], "count": r["n"]} for r in types],
            "by_language": [{"language": r["language"], "count": r["n"]} for r in langs],
            "last_7_days": [{"date": r["d"], "count": r["n"]} for r in reversed(week)],
            "privacy_note": "These numbers are computed from your own device only. No account, no tracking, no server-side profile.",
        }

    # --------------------------------------------------------------- scam iq
    def get_scam_iq(self, device_id: str) -> dict[str, Any]:
        rows = self.query("SELECT * FROM scam_iq WHERE device_id = ?", (device_id,))
        if not rows:
            return {
                "device_id": device_id, "score": 0, "streak_days": 0, "last_active_date": None,
                "lessons_completed": 0, "quizzes_passed": 0, "correct_answers": 0,
                "total_answers": 0, "badges": [],
            }
        return dict(rows[0])

    def upsert_scam_iq(self, device_id: str, **fields: Any) -> dict[str, Any]:
        current = self.get_scam_iq(device_id)
        merged = {**current, **fields}
        self.execute(
            "INSERT INTO scam_iq (device_id, score, streak_days, last_active_date, lessons_completed,"
            " quizzes_passed, correct_answers, total_answers, badges) VALUES (?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(device_id) DO UPDATE SET score=excluded.score, streak_days=excluded.streak_days,"
            " last_active_date=excluded.last_active_date, lessons_completed=excluded.lessons_completed,"
            " quizzes_passed=excluded.quizzes_passed, correct_answers=excluded.correct_answers,"
            " total_answers=excluded.total_answers, badges=excluded.badges",
            (
                device_id, int(merged.get("score", 0)), int(merged.get("streak_days", 0)),
                merged.get("last_active_date"), int(merged.get("lessons_completed", 0)),
                int(merged.get("quizzes_passed", 0)), int(merged.get("correct_answers", 0)),
                int(merged.get("total_answers", 0)), json.dumps(merged.get("badges", []), ensure_ascii=False),
            ),
        )
        return self.get_scam_iq(device_id)

    def record_lesson(self, device_id: str, pattern_id: str, correct: int, total: int) -> dict[str, Any]:
        today = date.today().isoformat()
        iq = self.get_scam_iq(device_id)
        last = iq.get("last_active_date")
        streak = int(iq.get("streak_days", 0))
        if last == today:
            pass
        elif last and last == (date.today() - timedelta(days=1)).isoformat():
            streak += 1
        else:
            streak = 1

        existing = self.query(
            "SELECT 1 FROM lesson_progress WHERE device_id = ? AND pattern_id = ?", (device_id, pattern_id)
        )
        self.execute(
            "INSERT OR REPLACE INTO lesson_progress (device_id, pattern_id, completed_at, quiz_correct, quiz_total)"
            " VALUES (?,?,?,?,?)",
            (device_id, pattern_id, datetime.now(timezone.utc).isoformat(), correct, total),
        )
        first_time = not existing
        passed = total > 0 and correct / total >= 0.6
        score_gain = (10 if first_time else 3) + correct * 4 + (5 if passed else 0)

        badges = iq.get("badges") or []
        if isinstance(badges, str):
            badges = json.loads(badges)
        badge_defs = [
            ("first_lesson", "First Steps", "You finished your first micro-lesson", 1, "lessons_completed"),
            ("five_lessons", "Pattern Spotter", "You finished 5 micro-lessons", 5, "lessons_completed"),
            ("ten_lessons", "Scam Scholar", "You finished 10 micro-lessons", 10, "lessons_completed"),
            ("perfect_quiz", "Sharp Eye", "You answered every quiz question correctly", None, None),
            ("three_day_streak", "Consistent Learner", "You learned 3 days in a row", 3, "streak_days"),
        ]
        lessons_completed = int(iq.get("lessons_completed", 0)) + (1 if first_time else 0)
        quizzes_passed = int(iq.get("quizzes_passed", 0)) + (1 if passed else 0)
        correct_answers = int(iq.get("correct_answers", 0)) + correct
        total_answers = int(iq.get("total_answers", 0)) + total

        have = {b["id"] for b in badges}
        for bid, title, desc, threshold, field_name in badge_defs:
            if bid in have:
                continue
            earned = False
            if bid == "perfect_quiz":
                earned = total > 0 and correct == total
            elif field_name == "lessons_completed":
                earned = lessons_completed >= threshold
            elif field_name == "streak_days":
                earned = streak >= threshold
            if earned:
                badges.append({"id": bid, "title": title, "description": desc,
                               "earned_at": datetime.now(timezone.utc).isoformat()})

        updated = self.upsert_scam_iq(
            device_id,
            score=int(iq.get("score", 0)) + score_gain,
            streak_days=streak,
            last_active_date=today,
            lessons_completed=lessons_completed,
            quizzes_passed=quizzes_passed,
            correct_answers=correct_answers,
            total_answers=total_answers,
            badges=badges,
        )
        updated["badges"] = badges
        updated["score_gain"] = score_gain
        updated["passed"] = passed
        updated["level"] = iq_level(int(updated.get("score", 0)))
        return updated


def iq_level(score: int) -> str:
    for threshold, name in [(900, "Guardian"), (600, "Protector"), (350, "Watcher"), (150, "Learner")]:
        if score >= threshold:
            return name
    return "Beginner"
