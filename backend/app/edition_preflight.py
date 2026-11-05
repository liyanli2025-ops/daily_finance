"""Read-only operator entry for the SAME production edition service. No --run."""
import argparse
import asyncio
import json


def main():
    parser = argparse.ArgumentParser(description='免费检查统一生成条件，不发起服务商请求')
    parser.add_argument('--report-type', choices=['morning', 'evening'], default='morning')
    args = parser.parse_args()
    from .services.edition_pipeline import preflight
    print(json.dumps(asyncio.run(preflight(args.report_type)), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
