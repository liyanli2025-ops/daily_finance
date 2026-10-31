"""Paused runtime-only repair from the user's confirmed immutable v19 package."""
import argparse,json
from pathlib import Path
from build_model_led_release import build

NAMES=('backend/app/services/web_research.py','backend/app/services/primary_discovery.py',
       'tools/run_primary_collection_once.py','tools/check_saved_search_bodies.py',
       'docs/reading_pipeline_repair_20261031.md')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path);parser.add_argument('--baseline',required=True,type=Path)
    args=parser.parse_args()
    result=build(args.output,args.baseline,expected_sha='2c17a1768c7fefd33f5782a63c566a97573262b6ec3e34b8337228cf9ea26e25',
                 prefix='finance-model-led-20261031-v19/',names=NAMES)
    print(json.dumps(result,ensure_ascii=False,indent=2))
