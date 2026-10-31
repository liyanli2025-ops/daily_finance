"""Print the local configured budget for a supplied size; never read App or call APIs."""
import argparse
import json

from .config import settings
from .services.discovery_budget import plan_budget
from .services.search_primary_collection import LANES


def main():
    parser = argparse.ArgumentParser(description='免费预算预览；数量为用户输入，不代表App实际名单')
    parser.add_argument('--watchlist-count', type=int, required=True)
    args = parser.parse_args()
    limits, ceiling, plan = plan_budget(args.watchlist_count, len(LANES), settings)
    print(json.dumps(dict(mode='local_budget_preview_no_execution',
        watchlist_count_source='explicit_argument_not_app_database', budget_plan=plan,
        model_requests=0, search_requests=0, http_requests=0, tts_requests=0,
        collection_executed=False), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
