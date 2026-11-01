"""Bounded, reversible views of private discovery receipts; no IO or model calls.

Directories are metadata, bodies retain exact offsets, and completed requests
are tracked separately from tool returns. Paging never alters the source state.
"""
import hashlib
import json
from collections import deque


CODEC = 'finance-discovery-context-v1'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def wire_size(value):
    """Characters contributed after the JSON view is embedded in a message."""
    return len(json.dumps(encoded(value), ensure_ascii=False))-2


def merged(ranges):
    result = []
    for start, end in sorted(ranges):
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


def subtract(start, end, ranges):
    cursor = start
    result = []
    for left, right in merged(ranges):
        if right <= cursor:
            continue
        if left >= end:
            break
        if left > cursor:
            result.append([cursor, min(left, end)])
        cursor = max(cursor, right)
    if cursor < end:
        result.append([cursor, end])
    return result


def body_packets(state):
    packets, seen = [], set()
    for receipt in state.get('receipts', []):
        result = receipt['result']
        material = result.get('material', result)
        if result.get('status') != 'ok' or not isinstance(material.get('text'), str) or not material.get('id'):
            continue
        offset = material.get('offset', 0)
        if type(offset) is not int or offset < 0 or not material['text']:
            continue
        key = (material['id'], offset, material['text'])
        if key not in seen:
            seen.add(key)
            packets.append(dict(material, offset=offset))
    return packets


def compact_candidate(identifier, row):
    # Keep the complete title, URL and provider snippet, not a new summary.
    result = dict(candidate_id=identifier, **{key: row[key] for key in
        ('title', 'url', 'snippet', 'published_hint', 'reading_status') if key in row})
    result['research_links'] = [dict(lane=link.get('lane'), scope=link.get('scope'),
        purpose=link.get('purpose')) for link in row.get('discovered_by', [])]
    result['retrieval_flags'] = sorted({flag for item in row.get('retrieval_assessments', [])
                                       for flag in item.get('flags', [])})
    return result


def receipt_view(index, receipt):
    result = dict(receipt['result'])
    if 'results' in result:
        result['results'] = [row['candidate_id'] for row in result['results']]
    material = result.get('material', result)
    if isinstance(material.get('text'), str):
        reference = dict(id=material.get('id'), offset=material.get('offset', 0),
                         characters=len(material['text']), text_in='body_packets_or_saved_receipt')
        if 'material' in result:
            result['material'] = reference
        else:
            result.pop('text', None)
            result['body_reference'] = reference
    return dict(receipt_index=index, request=receipt['request'], result=result)


def source_metadata(material):
    return {key:value for key,value in material.items()
            if key not in {'text','offset','has_more','next_offset','status'}}


def project(state, max_characters):
    """Fit a page without truncating snippets, quotes, or changing body offsets.

    Oversized individual metadata entries are explicitly deferred, never silently
    shortened. Raw receipts/candidates remain available in the private artifact.
    """
    packets = body_packets(state)
    delivery = state.get('context_delivery', {})
    delivered = delivery.get('body_ranges', {})
    candidates = list(state.get('candidates', {}).items())
    observations = state.get('observations', [])
    focus = state.get('context_focus', {})
    body_ranges = {}
    for packet in packets:
        body_ranges.setdefault(packet['id'], []).append([packet['offset'], packet['offset']+len(packet['text'])])
    pending = {key: [span for start, end in merged(ranges)
                    for span in subtract(start, end, delivered.get(key, []))]
               for key, ranges in body_ranges.items()}
    pending_chars = sum(end-start for ranges in pending.values() for start, end in ranges)
    view = dict(codec=CODEC, candidate_scope='search_directory_not_body',
        body_scope='exact_displayed_ranges_not_certified_full_text',
        counts=dict(candidates=len(candidates), receipts=len(state.get('receipts', [])),
                    observations=len(observations), bodies=len(body_ranges),
                    returned_body_characters=sum(end-start for spans in body_ranges.values() for start,end in merged(spans)),
                    unexposed_returned_characters=pending_chars),
        navigation=dict(tool='inspect_context', candidates={}, receipts={}, observations={}, bodies={}),
        candidates=[], body_index=[], body_packets=[], tool_history=[], observations=[],
        limitation='分页未展示不等于无资料；原文和完整回执保留。完整响应只证明文字已送达，不证明理解或核实。')
    # Leave room for exact pagination metadata after filling arrays.
    capacity = max_characters-800
    if wire_size(view) > capacity:
        raise ValueError('discovery_context_fixed_overhead')

    def add(field, value, budget):
        view[field].append(value)
        accepted = wire_size(view) <= capacity and wire_size(view[field]) <= budget
        if not accepted:
            view[field].pop()
        return accepted

    body_index = []
    for key, spans in body_ranges.items():
        material = next(packet for packet in packets if packet['id'] == key)
        body_index.append(dict(**source_metadata(material),
            returned_ranges=merged(spans), completed_request_ranges=delivered.get(key, []),
            unexposed_returned_ranges=pending[key]))
    body_start = focus.get('offset', 0) if focus.get('section') == 'bodies' else 0
    for row in body_index[body_start:]:
        if not add('body_index', row, max(400, capacity//10)):
            break
    view['navigation']['bodies'] = dict(offset=body_start, shown=len(view['body_index']),
        next_offset=(body_start+len(view['body_index']) if body_start+len(view['body_index']) < len(body_index) else None))

    # A requested already-returned range is a local re-presentation, not a GET.
    spans = []
    if focus.get('section') == 'body':
        key, offset = focus['id'], focus['offset']
        spans.extend((key, max(start, offset), end) for start,end in merged(body_ranges.get(key, [])) if end > offset)
    spans.extend((key, start, end) for key, ranges in pending.items() for start,end in ranges)
    if not spans:
        spans = [(key, start, end) for key,ranges in body_ranges.items() for start,end in merged(ranges)]
    # Give each source a first slice before one long article fills the page.
    queues = {}
    for key,start,end in spans:
        queues.setdefault(key,deque()).extend((key,left,min(left+4000,end)) for left in range(start,end,4000))
    spans=[]
    while any(queues.values()):
        for queue in queues.values():
            if queue:spans.append(queue.popleft())
    shown_ranges = {}
    indexed_sources = {row['id'] for row in view['body_index']}
    described_sources = set(indexed_sources)
    for key, start, end in spans:
        for left, right in subtract(start, end, shown_ranges.get(key, [])):
            cursor = left
            while cursor < right:
                original = next(packet for packet in packets if packet['id'] == key
                    and packet['offset'] <= cursor < packet['offset']+len(packet['text']))
                length = min(4000, right-cursor, original['offset']+len(original['text'])-cursor)
                while length:
                    text = original['text'][cursor-original['offset']:cursor-original['offset']+length]
                    packet = dict(id=key, offset=cursor, text=text,
                                  text_sha256=hashlib.sha256(text.encode()).hexdigest())
                    if key not in described_sources:
                        packet['source_metadata']=source_metadata(original)
                    if add('body_packets', packet, capacity*35//100):
                        described_sources.add(key)
                        break
                    length //= 2
                if not length:
                    break
                shown_ranges.setdefault(key, []).append([cursor,cursor+length])
                cursor += length
            if cursor < right:
                break

    seen = set(delivery.get('candidate_ids', []))
    first_unseen = next((i for i,(key,_) in enumerate(candidates) if key not in seen), 0)
    candidate_start = focus.get('offset', 0) if focus.get('section') == 'candidates' else first_unseen
    for key,row in candidates[candidate_start:]:
        if not add('candidates', compact_candidate(key,row), capacity*30//100):
            break
    view['navigation']['candidates'] = dict(offset=candidate_start, shown=len(view['candidates']),
        next_offset=(candidate_start+len(view['candidates']) if candidate_start+len(view['candidates']) < len(candidates) else None),
        oversized_entry=(candidates[candidate_start][0] if not view['candidates'] and candidate_start < len(candidates) else None))
    note_start = focus.get('offset', 0) if focus.get('section') == 'observations' else max(0, len(observations)-8)
    for row in observations[note_start:]:
        if not add('observations', row, capacity//10):
            break
    view['navigation']['observations'] = dict(offset=note_start, shown=len(view['observations']),
        next_offset=(note_start+len(view['observations']) if note_start+len(view['observations']) < len(observations) else None))
    receipts = state.get('receipts', [])
    history_start = focus.get('offset', 0) if focus.get('section') == 'receipts' else max(0, len(receipts)-12)
    for index in range(history_start, len(receipts)):
        if not add('tool_history', receipt_view(index, receipts[index]), capacity*15//100):
            break
    view['navigation']['receipts'] = dict(offset=history_start, shown=len(view['tool_history']),
        next_offset=(history_start+len(view['tool_history']) if history_start+len(view['tool_history']) < len(receipts) else None))
    if wire_size(view) > max_characters:
        raise ValueError('discovery_context_fixed_overhead')
    return view


def manifest(view):
    ranges = {}
    for row in view['body_packets']:
        ranges.setdefault(row['id'], []).append([row['offset'], row['offset']+len(row['text'])])
    return dict(codec=CODEC, characters=len(encoded(view)), serialized_characters=wire_size(view),
        body_ranges={key:merged(value) for key,value in ranges.items()},
        candidate_ids=[row['candidate_id'] for row in view['candidates']],
        receipt_indices=[row['receipt_index'] for row in view['tool_history']],
        counts=view['counts'], navigation=view['navigation'])


def confirm(state, sent):
    delivery = state.setdefault('context_delivery', dict(body_ranges={},candidate_ids=[]))
    for key, ranges in sent['body_ranges'].items():
        delivery['body_ranges'][key] = merged(delivery['body_ranges'].get(key, [])+ranges)
    delivery['candidate_ids'] = sorted(set(delivery['candidate_ids']) | set(sent['candidate_ids']))
    state.setdefault('context_requests', []).append(dict(sent, completed_response=True))


def validate_inspection(request, state):
    section = request.get('section')
    offset = request.get('offset')
    if type(offset) is not int or offset < 0:
        raise ValueError('discovery_context_offset_invalid')
    arrays = dict(candidates=state['candidates'], receipts=state['receipts'],
                  observations=state.get('observations', []),
                  bodies={row['id'] for row in body_packets(state)})
    if section == 'body':
        if not any(row['id'] == request.get('id') and row['offset'] <= offset < row['offset']+len(row['text'])
                   for row in body_packets(state)):
            raise ValueError('discovery_context_body_not_returned')
    elif section not in arrays or offset >= len(arrays[section]):
        raise ValueError('discovery_context_page_invalid')
    return dict(section=section, offset=offset, **({'id':request['id']} if section == 'body' else {}))


def retain_observations(state, data, workspace):
    rows = data.get('observations', [])
    if not isinstance(rows, list) or len(rows) > 8:
        raise ValueError('discovery_observations_invalid')
    checked = []
    delivered = state.get('context_delivery', {}).get('body_ranges', {})
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('discovery_observation_invalid')
        key, offset, quote, note = (row.get(name) for name in ('id', 'offset', 'quote', 'note'))
        item = workspace.documents.get(key)
        if (type(offset) is not int or offset < 0 or not isinstance(quote, str) or not 1 <= len(quote) <= 400
                or not isinstance(note, str) or not 1 <= len(note) <= 600 or item is None
                or item.content[offset:offset+len(quote)] != quote
                or subtract(offset, offset+len(quote), delivered.get(key, []))):
            raise ValueError('discovery_observation_not_exposed_quote')
        checked.append(dict(id=key, offset=offset, quote=quote, note=note,
                            status='model_interpretation_not_independently_verified'))
    archive = state.setdefault('observations', [])
    for row in checked:
        if row not in archive:
            archive.append(row)
