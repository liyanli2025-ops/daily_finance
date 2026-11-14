"""Default free preview; --run continues only this saved failed $1 edition."""
import argparse
import asyncio
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, default=Path('/var/www/finance-daily'))
    parser.add_argument('--prices', type=Path, default=Path('/tmp/daily-finance-material-continuation-v40/accepted-prices.json'))
    parser.add_argument('--replay', action='store_true')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--input-sha')
    parser.add_argument('--save-preview', type=Path)
    parser.add_argument('--run-from-preview', type=Path)
    parser.add_argument('--export', type=Path, default=Path('/tmp/daily-finance-v46-review.zip'))
    args = parser.parse_args()
    if any(p.is_symlink() for p in (args.project, *args.project.parents)):
        raise SystemExit('项目路径含软链，停止')
    sys.path.insert(0, str(args.project / 'backend'))
    from app import edition_once as entry
    from app.services import edition_agenda_resume as resume, edition_pipeline as core
    if args.replay:
        directory=core.run_path('edition-e0112bd1261b43b2b501c97558f8f8ba',core.ROOT/'manual-v45-fix1')
        state,pending,proof,_,_=resume.load_original(directory)
        from urllib.parse import urlsplit
        counts={}
        for receipt in state.get('issuer_http_receipts',[]):
            url=receipt['url'];host=urlsplit(url).hostname
            group=('index_batch' if host=='qt.gtimg.cn' and any(x in url for x in ('usDJI','hkHSI'))
                else 'stock_quote_batches' if host=='qt.gtimg.cn'
                else 'breadth_catalogue_pages' if 'getHQNodeData' in url
                else 'breadth_count_checks' if 'getHQNodeStockCount' in url
                else 'issuer_catalogues' if '/api/security/ann' in url
                else 'company_business_profiles' if 'CompanySurveyAjax' in url
                else 'company_financial_baselines')
            counts[group]=counts.get(group,0)+1
        result=dict(mode='offline_saved_agenda_audit_replay',original_error=state['error_code'],
            pending_topic_leads=pending,proof=proof,public_request_breakdown=counts,
            source_counts=entry.summary(state,directory)['source_counts'],
            model_requests=0,search_requests=0,public_fetch_attempts=0,tts_requests=0,
            original_files_unchanged=True,limitation='只复核已存选题与回执；未送达新正文，不证明候选新闻属实。')
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return
    config = entry.accepted_config(json.loads(resume.regular(args.prices).read_text()), '1')
    if args.run_from_preview:
        if not args.run:
            parser.error('--run-from-preview requires --run')
        saved=json.loads(resume.regular(args.run_from_preview).read_text())
        from datetime import datetime
        from app.services.time_context import china_now
        if (saved.get('mode') != 'same_edition_saved_agenda_continuation_preview'
                or saved.get('id') != 'edition-e0112bd1261b43b2b501c97558f8f8ba'
                or not saved.get('ready_to_run')
                or not datetime.fromisoformat(saved['prepared_at']) <= china_now() <= datetime.fromisoformat(saved['expires_at'])):
            raise ValueError('edition_agenda_resume_preview_expired_or_blocked')
        args.input_sha=saved['input_sha256']
    async def execute():
        state, directory, reused = await resume.continue_once(config,
            'edition-e0112bd1261b43b2b501c97558f8f8ba', root=core.ROOT/'manual-v45-fix1',
            run=args.run, input_sha=args.input_sha)
        if directory is None:
            if args.save_preview:
                if any(p.is_symlink() for p in (args.save_preview,*args.save_preview.parents)):
                    raise ValueError('edition_agenda_resume_preview_path_invalid')
                from app.services.research_hub import save_json
                save_json(args.save_preview,state)
            print(json.dumps(state, ensure_ascii=False, indent=2))
            return
        result = entry.summary(state, directory)
        result['existing_continuation_reused_no_new_requests'] = reused
        result['review_zip'] = str(entry.export_review(directory, args.export))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    asyncio.run(execute())


if __name__ == '__main__':
    main()
