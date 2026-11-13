"""Read-only operator entry for the production edition service. No --run."""
import argparse
import asyncio
import json
from pathlib import Path


def scenario_config(config, value):
    """A price-only, non-executable copy; never writes .env or accepts costs."""
    required = {'model_prices', 'search_price_usd', 'estimated_limit_usd'}
    if not isinstance(value, dict) or not required.issubset(value) or set(value) - required - {'as_of', 'sources', 'note'}:
        raise ValueError('edition_price_scenario_invalid')
    from .services.edition_budget import number
    prices = value['model_prices']
    if not isinstance(prices, dict) or not prices:
        raise ValueError('edition_price_scenario_invalid')
    for key, row in prices.items():
        if not isinstance(key, str) or not isinstance(row, dict) or set(row) != {'input', 'output', 'cache_read', 'cache_write'}:
            raise ValueError('edition_price_scenario_invalid')
        for item in row.values(): number(item)
    number(value['search_price_usd'])
    if number(value['estimated_limit_usd']) <= 0:
        raise ValueError('edition_estimate_limit_missing')
    return config.model_copy(update=dict(edition_price_table=prices,
        edition_search_price_usd=value['search_price_usd'],
        edition_estimated_limit_usd=value['estimated_limit_usd'], edition_estimate_accepted=False))


def main():
    parser = argparse.ArgumentParser(description='免费检查统一生成条件，不发起服务商请求')
    parser.add_argument('--report-type', choices=['morning', 'evening'], default='morning')
    parser.add_argument('--price-scenario', type=Path, help='仅本次免费试算使用；不保存价格、不接受费用、不恢复自动化')
    args = parser.parse_args()
    from .services.edition_pipeline import preflight
    from .config import settings
    config = settings
    if args.price_scenario:
        config = scenario_config(settings, json.loads(args.price_scenario.read_text()))
    result = asyncio.run(preflight(args.report_type, config=config))
    if args.price_scenario:
        result.update(mode='free_price_scenario', scenario_only=True, live_settings_changed=False,
            ready_to_run=False,
            limitation='公开价格情景，非账户合同；只试算、不保存、不接受费用、不联网。未知新目录/正文会增加规划，不能保证整期在此金额内完成。')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
