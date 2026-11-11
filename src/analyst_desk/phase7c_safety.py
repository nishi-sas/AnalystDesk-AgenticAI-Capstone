"""Phase 7C: fail-closed safety preflight before Reflexion is used by the Writer.

This checks the *local store* and delegates per-record editorial whitelist, age,
analyst isolation and scope checks to Phase 7B.  It never opens a portal,
invokes an LLM, changes SEC evidence, or executes retrieved instructions.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

from .phase7a_reflexion import ReflexionError, _validate_store
from .phase7b_reflexion import retrieve_editorial_lessons, validate_editorial_advice

# Exact schema of the Phase7A capture store; unknown schema means the opt-in
# agent must not consume it. No schema migrations take place in this reader.
_LESSON_COLUMNS = (
    'id', 'analyst_id', 'company_scope', 'source_thread_sha256',
    'source_draft_sha256', 'next_draft_sha256', 'claim_id',
    'failure_verdict', 'lesson_code', 'guidance', 'outcome', 'created_at',
)
_MAX_BYTES = 20_000_000
_MAX_ROWS = 10_000


def store_preflight(root: Path) -> str:
    """Return MISSING or HEALTHY; refuse inconsistent/unavailable stores.

    A missing store is normal for first-time users. An existing untrusted,
    unavailable, structurally changed, or corrupt DB is a hard error.
    """
    root = Path(root).resolve()
    # Refuse symlinks even if they resolve to a location within the project.
    # Resolving before this check would conceal symlinked store files.
    raw = root / 'data' / 'reflexion' / 'reflexion.sqlite3'
    try:
        if any(p.is_symlink() for p in (root / 'data', root / 'data' / 'reflexion', raw)):
            raise ReflexionError('UNTRUSTED_LESSON_STORE')
        path = _validate_store(root, 'data/reflexion/reflexion.sqlite3')
        if not path.exists():
            return 'MISSING'
        if not path.is_file() or path.is_symlink() or path.stat().st_size > _MAX_BYTES:
            raise ReflexionError('UNTRUSTED_LESSON_STORE')
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=3)) as conn:
            conn.execute('PRAGMA query_only=ON')
            integrity = conn.execute('PRAGMA quick_check(1)').fetchone()
            if integrity is None or integrity[0] != 'ok':
                raise ReflexionError('LESSON_STORE_INTEGRITY_FAILED')
            fields = tuple(row[1] for row in conn.execute('PRAGMA table_info(reflexion_lessons)'))
            if fields != _LESSON_COLUMNS:
                raise ReflexionError('LESSON_STORE_SCHEMA_UNTRUSTED')
            # Do not rely on a giant or uncontrolled database for optional memory.
            count = conn.execute('SELECT count(*) FROM reflexion_lessons').fetchone()[0]
            if type(count) is not int or count < 0 or count > _MAX_ROWS:
                raise ReflexionError('LESSON_STORE_SIZE_LIMIT')
        return 'HEALTHY'
    except ReflexionError:
        raise
    except (sqlite3.DatabaseError, OSError) as exc:
        # Never leak local paths, SQL errors, or credentials in evidence receipts.
        raise ReflexionError('LESSON_STORE_UNAVAILABLE_OR_CORRUPT') from exc


def guarded_editorial_lessons(root: Path, *, analyst_id: str,
                              company_scope: tuple[str, ...] = ('GOOGL', 'MSFT'),
                              exclude_thread_id: str | None = None,
                              max_lessons: int = 4,
                              ttl_days: int = 90) -> list[dict]:
    """Opt-in retrieval that refuses invalid stores before the LLM/MCP stage.

    With no store, the same parameter validation still runs in Phase7B,
    preserving its fail-closed invalid-identity behavior.
    """
    store_preflight(root)
    lessons = retrieve_editorial_lessons(
        root, analyst_id=analyst_id, company_scope=company_scope,
        exclude_thread_id=exclude_thread_id, max_lessons=max_lessons,
        ttl_days=ttl_days,
    )
    return validate_editorial_advice(lessons)
