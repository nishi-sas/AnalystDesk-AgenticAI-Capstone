"""Phase 7A: conservative Reflexion capture from verified Stage 4C-3 artifacts.

This module imports *critique observations*, not ground truth or instructions.
It never sends material to an LLM, calls MCP or changes a report.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .stage4b2_risk import THEME_IDS

ALLOWED_CLAIMS = frozenset((*THEME_IDS, 'executive_summary'))
SOURCE_STATUS = frozenset({'UNSUPPORTED', 'UNCERTAIN', 'SUPPORTED', 'NOT_REVIEWED'})
ALLOWED_PHASES = frozenset({'STAGE4C_REVIEW_BLOCKED', 'STAGE4C_READY_FOR_HUMAN_REVIEW',
                             'STAGE4C_REVISION_LIMIT_REACHED', 'STAGE4C_SEMANTIC_REVIEW_PENDING'})
GUIDANCE = {
    'UNSUPPORTED': ('SCOPE_TO_CANONICAL_EVIDENCE',
                    'Limit each claim to what its cited SEC passages substantiate.'),
    'UNCERTAIN': ('VERIFY_BEFORE_ASSERTING',
                  'Treat incomplete or ambiguous source support as uncertain; request verification.'),
}
_SHA = re.compile(r'^[a-f0-9]{64}$')
_ID = re.compile(r'^[A-Za-z0-9_-]{3,64}$')
_ARTIFACT = re.compile(r'^evidence/[A-Za-z0-9_-]{6,90}_v[0-2]_(?:draft\.md|review\.json)$')
_MANIFEST = re.compile(r'^evidence/[A-Za-z0-9_-]{6,90}_manifest\.json$')


class ReflexionError(ValueError):
    """A source receipt or store path did not pass conservative acceptance."""


def _read_artifact(root: Path, relative: str, limit: int) -> bytes:
    if not isinstance(relative, str) or not _ARTIFACT.fullmatch(relative.replace('\\', '/')):
        raise ReflexionError('INVALID_ARTIFACT_PATH')
    evidence_root = (root / 'evidence').resolve()
    if not evidence_root.is_relative_to(root):
        raise ReflexionError('EVIDENCE_DIRECTORY_UNTRUSTED')
    source = (root / relative).resolve()
    if not source.is_relative_to(evidence_root) or not source.is_file():
        raise ReflexionError('ARTIFACT_OUTSIDE_EVIDENCE')
    if source.stat().st_size > limit:
        raise ReflexionError('ARTIFACT_TOO_LARGE')
    return source.read_bytes()


def _parse_review(review: object, *, draft_sha: str, thread_id: str) -> dict:
    if not isinstance(review, dict) or review.get('status') != 'PASS' or review.get('phase') != 'STAGE4C_CRITIC_REPORT_READY':
        raise ReflexionError('INVALID_CRITIC_RECEIPT')
    for k, expected in [('draft_sha256', draft_sha), ('source_thread_id', thread_id),
                        ('critic_review_performed', True), ('human_report_approved', False),
                        ('report_submitted_for_review', False), ('publication_performed', False),
                        ('semantic_entailment_checked', False)]:
        if review.get(k) != expected or type(review.get(k)) is not type(expected):
            raise ReflexionError('INVALID_CRITIC_BINDING')
    findings = review.get('findings')
    if (not isinstance(findings, list) or not findings or len(findings) not in {len(THEME_IDS), len(ALLOWED_CLAIMS)}
            or review.get('claim_count') != len(findings)):
        raise ReflexionError('INVALID_CLAIM_INVENTORY')
    found = {}
    for item in findings:
        if (not isinstance(item, dict) or item.get('claim_id') not in ALLOWED_CLAIMS
                or item['claim_id'] in found or item.get('verdict') not in SOURCE_STATUS
                or item.get('human_verified') is not False
                or not isinstance(item.get('reason'), str) or not 8 <= len(item['reason']) <= 400):
            raise ReflexionError('INVALID_FINDING')
        found[item['claim_id']] = item['verdict']
    if set(found) not in {frozenset(THEME_IDS), ALLOWED_CLAIMS}:
        raise ReflexionError('INCOMPLETE_FINDINGS')
    if not isinstance(review.get('hard_blockers'), list):
        raise ReflexionError('INVALID_HARD_BLOCKERS')
    # Do not collect lessons from non-assessed or unreliable/truncated review contexts.
    eligible = (review.get('model_semantic_assessment_performed') is True
                and all(v != 'NOT_REVIEWED' for v in found.values())
                and not {'CANONICAL_SOURCE_CONTEXT_TRUNCATED', 'CRITIC_REASON_SCHEMA_BLOCKER'}.intersection(review['hard_blockers']))
    return {'verdicts': found, 'eligible': eligible}


def extract_lessons(root: Path, manifest_name: str) -> tuple[list[dict], dict]:
    """Validate versioned, hash-bound Stage 4C evidence; return categorical observations.

    No SEC text or model reasons are returned or persisted. The generated advice is static.
    """
    root = Path(root).resolve()
    relative = manifest_name.replace('\\', '/') if isinstance(manifest_name, str) else ''
    if not _MANIFEST.fullmatch(relative):
        raise ReflexionError('INVALID_MANIFEST_PATH')
    evidence_root = (root / 'evidence').resolve()
    if not evidence_root.is_relative_to(root):
        raise ReflexionError('EVIDENCE_DIRECTORY_UNTRUSTED')
    source = (root / relative).resolve()
    if not source.is_relative_to(evidence_root) or not source.is_file() or source.stat().st_size > 65536:
        raise ReflexionError('MANIFEST_NOT_ACCESSIBLE')
    try:
        manifest = json.loads(source.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise ReflexionError('INVALID_MANIFEST_JSON') from exc
    if (not isinstance(manifest, dict) or manifest.get('status') != 'PASS'
            or manifest.get('phase') not in ALLOWED_PHASES
            or any(manifest.get(k) is not False for k in ('human_report_approved', 'report_submitted_for_review', 'publication_performed'))):
        raise ReflexionError('UNAPPROVED_STAGE4C_REQUIRED')
    thread = manifest.get('thread_id')
    versions = manifest.get('versions')
    actions = manifest.get('revision_actions')
    if (not isinstance(thread, str) or not _ID.fullmatch(thread)
            or not isinstance(versions, list) or not 1 <= len(versions) <= 3
            or not isinstance(actions, list) or len(actions) != len(versions) - 1
            or manifest.get('revision_count') != len(actions)
            or type(manifest.get('max_revisions')) is not int
            or not 0 <= manifest['max_revisions'] <= 2 or len(actions) > manifest['max_revisions']):
        raise ReflexionError('INVALID_VERSION_CHAIN')
    parsed = []
    for idx, v in enumerate(versions):
        if not isinstance(v, dict) or v.get('version') != idx or not isinstance(v.get('draft_sha256'), str) or not _SHA.fullmatch(v['draft_sha256']):
            raise ReflexionError('INVALID_VERSION')
        draft_name = v.get('draft_path')
        review_name = v.get('review_path')
        if (not isinstance(draft_name, str) or not isinstance(review_name, str)
                or not draft_name.endswith(f'_v{idx}_draft.md')
                or not review_name.endswith(f'_v{idx}_review.json')):
            raise ReflexionError('VERSION_PATH_MISMATCH')
        # Paths must share one versioned prefix (and must be within evidence/).
        if draft_name[:-len('_draft.md')] != review_name[:-len('_review.json')]:
            raise ReflexionError('VERSION_PATH_MISMATCH')
        draft = _read_artifact(root, draft_name, 250_000)
        if (hashlib.sha256(draft).hexdigest() != v['draft_sha256'] and
                hashlib.sha256(draft.replace(b'\r\n', b'\n')).hexdigest() != v['draft_sha256']):
            # Stage4C3 writes text files with platform-native line endings on Windows.
            raise ReflexionError('DRAFT_SHA_MISMATCH')
        try:
            review = json.loads(_read_artifact(root, review_name, 110_000))
        except ValueError as exc:
            raise ReflexionError('INVALID_REVIEW_JSON') from exc
        verified = _parse_review(review, draft_sha=v['draft_sha256'], thread_id=thread)
        if v.get('hard_blockers') != review['hard_blockers']:
            raise ReflexionError('REVIEW_BLOCKER_MISMATCH')
        parsed.append({'sha': v['draft_sha256'], **verified})
    observations = []
    for idx, action in enumerate(actions):
        prior, subsequent = parsed[idx], parsed[idx + 1]
        targets = {k for k, v in prior['verdicts'].items() if v in GUIDANCE}
        if (not isinstance(action, dict) or action.get('revision') != idx + 1
                or not isinstance(action.get('revised_claim_ids'), list)
                or len(action['revised_claim_ids']) != len(targets)
                or set(action['revised_claim_ids']) != targets):
            raise ReflexionError('REVISION_TARGET_MISMATCH')
        if not prior['eligible'] or not subsequent['eligible']:
            continue
        for claim_id in sorted(targets):
            failure = prior['verdicts'][claim_id]
            category, guidance = GUIDANCE[failure]
            observations.append({
                'claim_id': claim_id, 'failure_verdict': failure,
                'lesson_code': category, 'guidance': guidance,
                'outcome': ('IMPROVED_ON_REREVIEW' if subsequent['verdicts'][claim_id] == 'SUPPORTED'
                            else 'STILL_UNRESOLVED'),
                'source_draft_sha256': prior['sha'],
                'next_draft_sha256': subsequent['sha'],
            })
    return observations, {'source_thread_sha256': hashlib.sha256(thread.encode()).hexdigest(),
                          'validated_versions': len(parsed), 'revisions': len(actions),
                          'eligible_review_pairs': sum(parsed[i]['eligible'] and parsed[i+1]['eligible'] for i in range(len(actions))) }


def _validate_store(root: Path, store_relative: str) -> Path:
    if store_relative != 'data/reflexion/reflexion.sqlite3':
        raise ReflexionError('INVALID_STORE_PATH')
    store_root = (root / 'data' / 'reflexion').resolve()
    path = (root / store_relative).resolve()
    if not store_root.is_relative_to(root) or not path.is_relative_to(store_root):
        raise ReflexionError('STORE_OUTSIDE_PROJECT')
    return path


def capture_manifest(root: Path, manifest_name: str, *, analyst_id: str,
                     company_scope: tuple[str, ...] = ('GOOGL', 'MSFT'),
                     store_relative: str = 'data/reflexion/reflexion.sqlite3') -> dict:
    """Opt-in import; no mutation of Stage 4C artifacts or security/portal state."""
    root = Path(root).resolve()
    if not isinstance(analyst_id, str) or not _ID.fullmatch(analyst_id):
        raise ReflexionError('INVALID_ANALYST_ID')
    if (not isinstance(company_scope, tuple) or not company_scope
            or tuple(sorted(set(company_scope))) != company_scope
            or any(c not in {'MSFT', 'GOOGL'} for c in company_scope)):
        raise ReflexionError('INVALID_COMPANY_SCOPE')
    lessons, validated = extract_lessons(root, manifest_name)
    store = _validate_store(root, store_relative)
    store.parent.mkdir(parents=True, exist_ok=True)
    inserted = 0
    with closing(sqlite3.connect(store, timeout=5)) as conn:
        conn.execute('PRAGMA busy_timeout=5000')
        with conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS reflexion_lessons (
                id INTEGER PRIMARY KEY,
                analyst_id TEXT NOT NULL, company_scope TEXT NOT NULL,
                source_thread_sha256 TEXT NOT NULL,
                source_draft_sha256 TEXT NOT NULL, next_draft_sha256 TEXT NOT NULL,
                claim_id TEXT NOT NULL, failure_verdict TEXT NOT NULL,
                lesson_code TEXT NOT NULL, guidance TEXT NOT NULL, outcome TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(analyst_id, company_scope, source_thread_sha256, source_draft_sha256, claim_id)
            )''')
            for lesson in lessons:
                cursor = conn.execute('''INSERT OR IGNORE INTO reflexion_lessons
                    (analyst_id, company_scope, source_thread_sha256, source_draft_sha256,
                    next_draft_sha256, claim_id, failure_verdict, lesson_code, guidance, outcome)
                    VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (analyst_id, ','.join(company_scope), validated['source_thread_sha256'],
                     lesson['source_draft_sha256'], lesson['next_draft_sha256'], lesson['claim_id'],
                     lesson['failure_verdict'], lesson['lesson_code'], lesson['guidance'], lesson['outcome']))
                inserted += cursor.rowcount
            total = conn.execute('SELECT count(*) FROM reflexion_lessons WHERE analyst_id=? AND company_scope=?',
                                 (analyst_id, ','.join(company_scope))).fetchone()[0]
    return {'phase': 'PHASE7A_REFLEXION_CAPTURE', 'status': 'PASS',
            'scope': 'STRUCTURED_CRITIC_OBSERVATIONS_ONLY', 'manifest': manifest_name,
            'validated_versions': validated['validated_versions'],
            'revisions': validated['revisions'], 'eligible_review_pairs': validated['eligible_review_pairs'],
            'lesson_candidates': len(lessons), 'new_lessons': inserted,
            'stored_lessons_for_analyst_scope': total, 'deduplicated': len(lessons) - inserted,
            'raw_critic_text_stored': False, 'model_prompts_modified': False,
            'human_approval_performed': False, 'portal_publication_performed': False,
            'advisory_only': True,
            'limitations': ['Critic judgments are provisional model assessments, not verified facts',
                            'No lessons are applied to Writer or Critic until Phase 7B',
                            'No cross-user or cross-company retrieval is permitted']}
