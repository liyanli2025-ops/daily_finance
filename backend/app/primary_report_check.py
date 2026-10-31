"""Default: offline report-input preparation. --generate is an explicit paid action."""
import argparse
import asyncio
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True,
                        help='主动取材的 report-input.json 或显式主资料包')
    parser.add_argument('--generate', action='store_true')
    parser.add_argument('--input-sha', help='免费预览显示的输入指纹')
    parser.add_argument('--report-type', choices=('morning', 'evening'), default='morning')
    args = parser.parse_args()
    if args.generate and not args.input_sha:
        parser.error('--generate requires --input-sha from the reviewed offline preview')
    if args.input.is_symlink() or not args.input.is_file() or args.input.stat().st_size > 16 * 1024 * 1024:
        parser.error('input must be a regular JSON file no larger than 16 MiB')
    value = json.loads(args.input.read_bytes())
    from .services.primary_report import prepare, PrimaryReportService
    if args.generate:
        result = asyncio.run(PrimaryReportService().generate(value, args.input_sha, args.report_type))
    else:
        _, _, result = prepare(value)
        from .config import settings
        from .services.model_gateway import MODEL_PAUSE_FILE
        from .services.primary_report import OWNER
        prior = (value.get('upstream_usage') or {}).get('model_calls') if value.get('owner') == OWNER else None
        from .services.discovery_completion import CONTRACT
        independent=value.get('budget_contract')==CONTRACT
        result.update(automation_paused=MODEL_PAUSE_FILE.exists(),
            execution_limits=dict(max_model_requests=settings.model_max_calls_per_report,
                upstream_model_requests=prior,
                budget_mode='independent_report_phase' if independent else 'legacy_shared',
                max_new_model_requests=(settings.model_max_calls_per_report if independent else
                    max(0, settings.model_max_calls_per_report-prior) if type(prior) is int else settings.model_max_calls_per_report),
                retries=settings.model_http_retries, automatic_report_repair=settings.report_auto_repair_enabled,
                paid_search_requests=0, tts_requests=0, app_writes=0),
            generation_requires_explicit_paid_action=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        import re
        code=str(error)
        print(json.dumps(dict(status='stopped',error_type=type(error).__name__,
            reason=code if re.fullmatch(r'primary_report_[a-z_]+',code) else 'input_or_runtime_unavailable'),
            ensure_ascii=False))
        raise SystemExit(2)
