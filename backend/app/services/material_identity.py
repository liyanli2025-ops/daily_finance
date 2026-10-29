"""Separate a research source document from its scoped stored-text views."""
from dataclasses import replace
import hashlib


def source_id(kind,url,period):
    # Matches the legacy source-document identity, independent of stock scope.
    return hashlib.sha256((kind+url+period).encode()).hexdigest()[:24]


def normalize_view(material):
    # Government adapters retain different original paragraphs by business
    # family. Legacy cache IDs used URL/period alone, colliding across bodies.
    if material.kind=='industry_observation':
        identity=source_id(material.kind,material.source_url,material.period)
        key=hashlib.sha256((identity+'\0'+material.body).encode()).hexdigest()[:24]
        return replace(material,id=key)
    return material


def scope_links(material):
    return sorted({scope.strip() for scope in material.scope.split('；') if scope.strip()})


def merge_same_view(first,second):
    # Unexpected collisions still stop; never silently choose one conflicting text.
    fields=('id','body','kind','source_url','period','published_at')
    if any(getattr(first,key)!=getattr(second,key) for key in fields):
        raise ValueError('research_material_identity_collision')
    scopes=sorted(set(scope_links(first)+scope_links(second)))
    status='；'.join(dict.fromkeys([first.reading_status,second.reading_status]))
    return replace(first,scope='；'.join(scopes),reading_status=status)


def coalesce_materials(materials):
    result={}
    for value in materials:
        material=normalize_view(value)
        if material.id in result:material=merge_same_view(result[material.id],material)
        result[material.id]=material
    return list(result.values())
