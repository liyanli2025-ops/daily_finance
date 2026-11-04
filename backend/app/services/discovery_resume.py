"""Restore a stopped collection without I/O to providers or resetting counters."""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from .discovery_budget import Limits
from .discovery_context import body_packets, merged, subtract
from .search_objectives import infer_purpose


def tool_caches(state):
    """Reuse attempted queries/URLs, including failed paths, with original IDs."""
    searches, reads = {}, {}
    for receipt in state.get('receipts', []):
        request, result = receipt['request'], receipt['result']
        if request.get('tool') == 'search' and result.get('status') in {'ok', 'failed', 'unavailable', 'disabled'}:
            query = ' '.join(request['query'].split())
            purpose = request.get('purpose') or infer_purpose(query, request['lane'])
            topic = request.get('topic', 'news' if purpose == 'latest_close' else 'general')
            searches.setdefault((query, topic, purpose), deepcopy(result))
        if request.get('tool') == 'read' and request.get('candidate_id') in state.get('candidates', {}):
            # Company/landing/unsupported rejections never attempted a fetch.
            if result.get('status') in {'ok', 'failed', 'unavailable'}:
                url = state['candidates'][request['candidate_id']]['url']
                reads.setdefault(url, deepcopy(result))
    return searches, reads


def restore_state(workspace, stocks, resume, settings):
    """Only a proven input-size stop may resume; same envelope and cutoff."""
    state = deepcopy(resume['research'])
    if (state.get('owner') != 'finance-model-led-discovery-v1'
            or state.get('status') != 'input_budget_exhausted'
            or state.get('watchlist') != stocks
            or state.get('started_at') != workspace.now.isoformat()
            or state['budget_plan'].get('mode') != 'progress_driven_collection'):
        raise ValueError('discovery_resume_identity_or_stop_invalid')
    spent = resume['active_seconds']
    if type(spent) is not int or spent < 0:
        raise ValueError('discovery_resume_active_time_invalid')
    plan = state['budget_plan']
    limits, ceiling = Limits(**state['limits']), Limits(**plan['ceiling'])
    for field, configured in (
            ('search_calls', settings.research_web_search_max_requests),
            ('body_urls', settings.research_body_max_urls),
            ('local_read_characters', settings.research_local_read_max_characters),
            ('input_characters', settings.research_input_max_characters),
            ('seconds', settings.research_max_seconds)):
        if getattr(ceiling, field) > configured or getattr(limits, field) > getattr(ceiling, field):
            raise ValueError('discovery_resume_resource_envelope_changed')
    if (plan['total_input_characters'] > settings.research_total_input_characters
            or plan['total_reserved_output_tokens'] > settings.research_total_output_tokens
            or plan.get('model_request_cap') != settings.research_max_model_calls):
        raise ValueError('discovery_resume_model_envelope_changed')
    for key in ('model_calls', 'model_input_characters', 'reserved_output_tokens',
                'search_tool_calls', 'body_url_calls', 'local_read_characters', 'no_progress_turns'):
        if type(state[key]) is not int or state[key] < 0:
            raise ValueError('discovery_resume_usage_invalid')
    if (spent >= limits.seconds or state['no_progress_turns'] >= 2
            or state['model_input_characters'] >= plan['total_input_characters']
            or state['reserved_output_tokens'] + limits.output_tokens > plan['total_reserved_output_tokens']):
        raise ValueError('discovery_resume_original_envelope_exhausted')
    if getattr(workspace, 'web_search_attempts', None) != resume['search_http_attempts']:
        raise ValueError('discovery_resume_search_counter_changed')
    packets = body_packets(state)
    allowed = {}
    for packet in packets:
        key, offset, text = packet['id'], packet['offset'], packet['text']
        item = workspace.documents.get(key)
        if item is None or item.content[offset:offset+len(text)] != text:
            raise ValueError('discovery_resume_source_text_changed')
        allowed.setdefault(key, []).append([offset, offset+len(text)])
    if not set(state['provided_ids']) <= set(allowed):
        raise ValueError('discovery_resume_provided_ids_changed')
    delivery = dict(body_ranges={}, candidate_ids=[])
    exposures = resume['model_exposures']
    if len(exposures) != state['model_calls']:
        raise ValueError('discovery_resume_exposure_count_changed')
    for exposure in exposures:
        if not exposure['completed_response']:
            continue
        for key, ranges in exposure['body_ranges'].items():
            for start, end in ranges:
                if (type(start) is not int or type(end) is not int or not 0 <= start < end
                        or key not in allowed or subtract(start, end, merged(allowed[key]))):
                    raise ValueError('discovery_resume_unprovided_model_exposure')
            delivery['body_ranges'][key] = merged(delivery['body_ranges'].get(key, [])+ranges)
    # Historic requests without candidate manifests do not prove any directory
    # page was delivered. Never import the offline replay's simulated delivery.
    state['context_delivery'] = delivery
    state.setdefault('observations', [])
    state.pop('context_focus', None)
    state.pop('request_context', None)
    state.update(status='running', phase='resume_saved_context',
                 resumed_from_status='input_budget_exhausted', prior_active_seconds=spent)
    return state, limits, ceiling, plan, spent


def stored_news(row):
    """Keep original publication labels, including day-only uncertainty."""
    from ..models.news import News
    from .evidence import publication_label
    from .news_quality import reading_scope
    if row.get('kind', 'news') != 'news':
        raise ValueError('discovery_resume_material_kind_requires_specific_loader')
    published = row['published']
    impact = None
    if published.endswith('（日精度；内部日期区间起点不是实际发布时分）'):
        raw = published.split('（日精度；', 1)[0]
        stamp = datetime.fromisoformat(raw[:10])
        impact = '原始来源时点：'+raw+'；精度：day；从已存正文恢复'
    elif published.endswith('（分钟精度）'):
        raw = published[:-len('（分钟精度）')]
        stamp = datetime.fromisoformat(raw)
        impact = '原始来源时点：'+raw+'；精度：minute；从已存正文恢复'
    else:
        stamp = datetime.fromisoformat(published)
    item = News(id=row['id'], title=row['title'], source=row['source'], source_url=row['url'],
                content=row['text'], published_at=stamp, market_impact=impact)
    if (len(item.content) != row['characters'] or publication_label(item) != published
            or reading_scope(item) != row['reading_scope']):
        raise ValueError('discovery_resume_metadata_not_lossless')
    return item


def clone_workspace(source, now, workspace_type=None):
    """Small local fork: old materials/result/HTTP captures stay immutable."""
    from .episode_workspace import EpisodeWorkspace, body
    from .research_hub import save_json
    source = Path(source)
    if source.is_symlink() or any(p.is_symlink() for p in source.rglob('*')):
        raise ValueError('discovery_resume_workspace_symlink')
    rows = json.loads((source/'materials.json').read_text(encoding='utf-8'))
    items = [stored_news(row) for row in rows]
    if len({item.id for item in items}) != len(items):
        raise ValueError('discovery_resume_duplicate_material')
    meta = json.loads((source/'meta.json').read_text(encoding='utf-8'))
    if meta.get('owner') != 'finance-episode-v1':
        raise ValueError('discovery_resume_workspace_owner')
    workspace = object.__new__(workspace_type or EpisodeWorkspace)
    workspace.root = source.parent
    workspace.path = Path(tempfile.mkdtemp(prefix='episode-', dir=source.parent))
    workspace.now = datetime.fromisoformat(meta['created_at'])
    workspace.documents = {item.id:item for item in items}
    workspace.document_hashes = {item.id:hashlib.sha256(body(item).encode()).hexdigest() for item in items}
    workspace.accessed = {}; workspace.journal = []; workspace.catalogue_refs = {}
    workspace.prepared = {}; workspace.confirmed = {}; workspace.completed_rounds = 0
    workspace.cited_ids = set(); workspace.claim_refs = []
    workspace.meta = dict(meta, status='working', resumed_from=source.name,
        resumed_at=now.isoformat(), expires_at=(now+timedelta(hours=24)).isoformat())
    shutil.copyfile(source/'materials.json', workspace.path/'materials.json')
    if (source/'public-responses').is_dir():
        shutil.copytree(source/'public-responses', workspace.path/'public-responses')
    save_json(workspace.path/'meta.json', workspace.meta)
    return workspace
