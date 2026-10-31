"""Local runtime inspection or offline saved-response review. Never fetches URLs."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--captures', type=Path, help='本期 public-responses 目录')
    parser.add_argument('--hours', type=int, default=72)
    parser.add_argument('--write-review', action='store_true',
                        help='在原始快照目录内新建私有验收子目录，随原 episode 到期清理')
    args = parser.parse_args()
    if not 1 <= args.hours <= 168:
        parser.error('--hours must be between 1 and 168')
    if args.captures is None:
        if args.write_review:
            parser.error('--write-review requires --captures')
        from .services.generic_extraction import runtime_status
        result = dict(mode='local_import_inspection', extractor=runtime_status(),
                      http_requests=0, model_requests=0, search_requests=0, tts_requests=0,
                      limitation='只检查依赖能否导入，未验证真实网页、服务器网络或资料质量。')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['extractor']['ready'] else 2
    from .services.reading_acceptance import replay, render_review, check_directory
    result = replay(args.captures, hours=args.hours)
    if args.write_review:
        # A unique child preserves prior reports and the episode's existing TTL.
        import os
        import tempfile
        folder = Path(tempfile.mkdtemp(prefix='reading-review-', dir=check_directory(args.captures)))
        for name, content in (('result.json', json.dumps(result, ensure_ascii=False, indent=2)),
                              ('review.md', render_review(result))):
            with (folder / name).open('x', encoding='utf-8') as stream:
                os.chmod(stream.name, 0o600)
                stream.write(content)
        result['review_directory'] = str(folder)
    # Raw article text stays in the private report, not shared terminal logs.
    print(json.dumps({key: value for key, value in result.items() if key != 'rows'},
                     ensure_ascii=False, indent=2))
    return 0 if result['counts'].get('parser_admitted_pending_human_review') else 2


if __name__ == '__main__':
    raise SystemExit(main())
