"""Phase 7B: opt-in, bounded editorial guidance from Phase 7A observations.

Only source-code-authored whitelist guidance can reach the Writer; database
text is never authority, source evidence, or a permission to approve reports.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import re
import sqlite3

from .phase7a_reflexion import GUIDANCE, ALLOWED_CLAIMS, ReflexionError, _validate_store

_ID = re.compile(r'^[A-Za-z0-9_-]{3,64}$')
_SHA = re.compile(r'^[0-9a-f]{64}$')


def validate_editorial_advice(lessons: object) -> list[dict]:
    """Accept only bounded editorial hints matching source-code templates."""
    if not isinstance(lessons, list) or len(lessons) > 6:
        raise ReflexionError('INVALID_EDITORIAL_ADVICE')
    seen = set()
    clean = []
    for lesson in lessons:
        if not isinstance(lesson, dict) or set(lesson) != {'claim_id', 'lesson_code', 'guidance'}:
            raise ReflexionError('INVALID_EDITORIAL_ADVICE')
        claim, code, guidance = lesson['claim_id'], lesson['lesson_code'], lesson['guidance']
        if (claim not in ALLOWED_CLAIMS or not any((code, guidance) == pair for pair in GUIDANCE.values())
                or (claim, code) in seen):
            raise ReflexionError('INVALID_EDITORIAL_ADVICE')
        seen.add((claim, code))
        clean.append({'claim_id': claim, 'lesson_code': code, 'guidance': guidance})
    return clean


def retrieve_editorial_lessons(root: Path, *, analyst_id: str,
                               company_scope: tuple[str, ...] = ('GOOGL', 'MSFT'),
                               exclude_thread_id: str | None = None,
                               max_lessons: int = 4, ttl_days: int = 90) -> list[dict]:
    """Exact tenant/scope match; improved outcomes only; read-only SQLite.

    Missing database => no lessons. A malformed existing database => fail-closed.
    No free-form stored string becomes a prompt instruction.
    """
    root = Path(root).resolve()
    if not isinstance(analyst_id, str) or not _ID.fullmatch(analyst_id):
        raise ReflexionError('INVALID_ANALYST_ID')
    if (not isinstance(company_scope, tuple) or not company_scope
            or tuple(sorted(set(company_scope))) != company_scope
            or not set(company_scope).issubset({'MSFT', 'GOOGL'})):
        raise ReflexionError('INVALID_COMPANY_SCOPE')
    if exclude_thread_id is not None and (not isinstance(exclude_thread_id, str)
                                          or not _ID.fullmatch(exclude_thread_id)):
        raise ReflexionError('INVALID_SOURCE_THREAD')
    if type(max_lessons) is not int or not 1 <= max_lessons <= 6:
        raise ReflexionError('INVALID_LESSON_LIMIT')
    if type(ttl_days) is not int or not 1 <= ttl_days <= 365:
        raise ReflexionError('INVALID_LESSON_AGE')
    store = _validate_store(root, 'data/reflexion/reflexion.sqlite3')
    if not store.exists():
        return []
    if not store.is_file() or store.is_symlink() or store.stat().st_size > 20_000_000:
        raise ReflexionError('UNTRUSTED_LESSON_STORE')
    exclude_sha = hashlib.sha256(exclude_thread_id.encode()).hexdigest() if exclude_thread_id else ''
    try:
        with closing(sqlite3.connect(store.as_uri() + '?mode=ro', uri=True, timeout=3)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute('''SELECT claim_id, failure_verdict, lesson_code, guidance,
                    outcome, source_thread_sha256, source_draft_sha256, next_draft_sha256,
                    created_at FROM reflexion_lessons
                    WHERE analyst_id=? AND company_scope=? AND outcome='IMPROVED_ON_REREVIEW'
                    AND source_thread_sha256<>?
                    ORDER BY created_at DESC, id DESC LIMIT ?''',
                    (analyst_id, ','.join(company_scope), exclude_sha, max_lessons * 8)).fetchall()
    except sqlite3.DatabaseError as exc:
        raise ReflexionError('INVALID_LESSON_STORE') from exc
    cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    result = []
    seen = set()
    for item in rows:
        try:
            created = datetime.strptime(item['created_at'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        except (ValueError, TypeError) as exc:
            raise ReflexionError('INVALID_LESSON_TIMESTAMP') from exc
        if created < cutoff or created > datetime.now(timezone.utc) + timedelta(minutes=5):
            continue
        claim, verdict, code = item['claim_id'], item['failure_verdict'], item['lesson_code']
        if (claim not in ALLOWED_CLAIMS or verdict not in GUIDANCE
                or (code, item['guidance']) != GUIDANCE[verdict]
                or not all(isinstance(item[key], str) and _SHA.fullmatch(item[key])
                           for key in ('source_thread_sha256', 'source_draft_sha256', 'next_draft_sha256'))
                or item['source_draft_sha256'] == item['next_draft_sha256']):
            raise ReflexionError('INVALID_LESSON_RECORD')
        if (claim, code) in seen:
            continue
        seen.add((claim, code))
        result.append({'claim_id': claim, 'lesson_code': code, 'guidance': GUIDANCE[verdict][1]})
        if len(result) >= max_lessons:
            break
    return validate_editorial_advice(result)
