"""Review one saved episode's acquisition state; never call models or networks."""
import argparse
import json
from pathlib import Path
import re

from .services.discovery_completion import completion_review


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--episode',required=True,help='现有episode目录名，不接受路径')
    args=parser.parse_args()
    if not re.fullmatch(r'episode-[A-Za-z0-9_-]{1,80}',args.episode):
        parser.error('episode must be a single episode directory name')
    root=Path(__file__).absolute().parents[1]/'data'/'episodes'
    folder=root/args.episode
    source=folder/'primary-discovery.json'
    if (root.is_symlink() or root.parent.is_symlink() or folder.is_symlink() or source.is_symlink()
            or not source.is_file() or source.stat().st_size>32*1024*1024):
        parser.error('saved episode state missing or invalid')
    state=json.loads(source.read_bytes())
    if state.get('owner')!='finance-model-led-discovery-v1':
        parser.error('not a discovery episode')
    review=completion_review(state)
    candidates=[dict(candidate_id=key,title=row.get('title'),url=row.get('url'))
                for key,row in state.get('candidates',{}).items()]
    bodies=[{key:row[key] for key in ('id','characters','ranges','unread_ranges','eligible')}
            for row in state.get('collection_feedback',{}).get('bodies',{}).values()]
    print(json.dumps(dict(mode='saved_collection_review_no_execution',review=review,candidates=candidates,
        bodies=bodies,model_requests=0,search_requests=0,http_requests=0,tts_requests=0),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
