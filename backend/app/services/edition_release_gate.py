"""Release evidence for explicit paid acceptance. Never certifies news truth."""
import hashlib
import json
from pathlib import Path

OWNER = 'finance-critical-path-acceptance-v1'
CASES = {
    'issuer_full_path': 'reviewed_text',
    'real_v45_partial': 'partial_materials',
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
