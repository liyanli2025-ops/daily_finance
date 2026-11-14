"""Release evidence for explicit paid acceptance. Never certifies news truth."""
import hashlib
import json
from pathlib import Path

OWNER = 'finance-critical-path-acceptance-v1'
CASES = {
    'real_v49_assessment': 'partial_materials',
    'issuer_full_path': 'reviewed_text',
    'real_v45_partial': 'partial_materials',
    'real_v47_input': 'partial_materials',
    'real_evidence_screening': 'cleaned_with_verification_gaps',
    'no_body': 'partial_materials',
    'model_402': 'failed',
    'invalid_quote': 'partial_materials',
    'oversized_input': 'failed',
    'interrupted_read': 'interrupted',
    'persistence_failure': 'failed_before_request',
    'repeat_failed_run': 'reused_no_requests',
    'missing_concrete_topic': 'partial_materials',
}
REQUIRED_FLOW = ['reading', 'assessment', 'assessment_validated', 'materials_decision',
                 'writing', 'review', 'review_validated']
ROOT = Path(__file__).resolve().parents[2]/'data/diagnostics/release-acceptance'


def validate_evidence(value):
    if not isinstance(value, dict):
        raise ValueError('edition_release_evidence_incomplete')
    cases = value.get('cases', {})
    if (value.get('owner') != OWNER or value.get('network_connections') != 0
            or value.get('paid_provider_requests') != 0 or set(cases) != set(CASES)):
        raise ValueError('edition_release_evidence_incomplete')
    for name, expected in CASES.items():
        row = cases[name]
        if not isinstance(row, dict) or row.get('outcome') != expected or row.get('assertions_passed') is not True:
            raise ValueError('edition_release_case_not_passed')
    flow = cases['issuer_full_path']
    if (flow.get('flow') != REQUIRED_FLOW or flow.get('model_http_attempts') != 4
            or flow.get('issuer_text_pages') != 3 or flow.get('body_characters') != 10318
            or not flow.get('original_text_sha256') or flow.get('app_written') is not False
            or flow.get('tts_requests') != 0):
        raise ValueError('edition_release_full_path_not_exercised')
    real = cases['real_v47_input']
    if (real.get('original_characters',0) < 85002 or not 0 < real.get('request_characters',0) <= 65000
            or real.get('input_limit') != 65000 or real.get('article_bodies') != 5
            or real.get('candidate_titles') != 65 or real.get('original_sources_unchanged') is not True
            or real.get('new_model_requests') != 1 or real.get('new_search_requests') != 0
            or real.get('new_public_requests') != 0 or real.get('old_public_requests') != 127
            or real.get('estimated_limit_usd') != '1' or real.get('missing_election_preserved') is not True):
        raise ValueError('edition_release_real_multiple_bodies_not_exercised')
    quality=cases['real_evidence_screening']
    if (quality.get('article_bodies')!=5 or quality.get('removed_characters',0)<=0
            or quality.get('pending_verification')!=2 or quality.get('commentary')!=1
            or quality.get('issuer_bodies_unchanged') is not True or quality.get('unsafe_quotes_blocked') is not True):
        raise ValueError('edition_release_evidence_screening_not_exercised')
    protocol=cases['real_v49_assessment']
    if (protocol.get('new_model_requests')!=0 or protocol.get('new_search_requests')!=0
            or protocol.get('new_public_requests')!=0 or protocol.get('ready_events')!=['E6','E7']
            or protocol.get('missing_change_tasks')!=13 or protocol.get('missing_topics')!=2
            or protocol.get('rejected_searches')!=2 or protocol.get('old_files_unchanged') is not True
            or protocol.get('accounted_estimate_usd')!='0.272476'):
        raise ValueError('edition_release_real_protocol_failure_not_exercised')
    return value


def require_acceptance(path=None):
    from .edition_pipeline import source_signature
    signature = source_signature()
    path = Path(path) if path is not None else ROOT/(signature+'.json')
    if any(p.is_symlink() for p in (path,*path.parents)) or not path.is_file():
        raise ValueError('edition_release_acceptance_missing')
    value = json.loads(path.read_text())
    if value.get('source_signature') != signature:
        raise ValueError('edition_release_acceptance_stale')
    validate_evidence(value)
    return dict(source_signature=signature, receipt_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
