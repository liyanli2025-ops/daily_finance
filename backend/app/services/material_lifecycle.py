"""Expire owned transient text caches; never touch App reports, audio, keys or backups."""
from datetime import datetime,timedelta
import json
from pathlib import Path

from .episode_workspace import EpisodeWorkspace
from .time_context import china_now

DATA=Path(__file__).resolve().parents[2]/'data'


def prune_material_caches(base=None,now=None):
    base=(Path(base) if base is not None else DATA).resolve();now=now or china_now()
    cutoff=now-timedelta(hours=24);removed=[]
    candidates=[]
    for relative in ('research/cache','research/stocks','radar/cache'):
        folder=base/relative
        if folder.is_symlink() or not folder.resolve().is_relative_to(base):continue
        if folder.is_dir():candidates.extend(folder.glob('*.json'))
    diagnostics=base/'diagnostics'
    if diagnostics.is_dir() and not diagnostics.is_symlink():
        for pattern in ('generation-*.json','review-*.json','text-acceptance-*.json','spoken-*.json'):
            candidates.extend(diagnostics.glob(pattern))
    for name in ('news-acceptance.json','technical.json','microstructure.json'):
        candidates.append(base/'radar'/name)
    for path in candidates:
        if path.is_symlink() or not path.resolve().is_relative_to(base) or not path.is_file():continue
        try:
            data=json.loads(path.read_text(encoding='utf-8'))
            value=data.get('collected_at',data.get('at')) if isinstance(data,dict) else None
            stamp=datetime.fromisoformat(value) if value else datetime.fromtimestamp(path.stat().st_mtime)
            if stamp.tzinfo is not None:
                from datetime import timezone
                stamp=stamp.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
            if stamp>cutoff:continue
            path.unlink();removed.append(str(path.relative_to(base)))
        except (OSError,ValueError,TypeError):continue
    return dict(expiry_hours=24,removed=removed,
        episode_directories_removed=EpisodeWorkspace.prune(base/'episodes',now))
