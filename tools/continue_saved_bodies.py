"""Default free input/cost preview; --run is explicit and single-attempt."""
import argparse,asyncio,json,sys
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,default=Path('/var/www/finance-daily'))
    p.add_argument('--prices',type=Path,default=Path('/tmp/daily-finance-material-continuation-v40/accepted-prices.json'))
    p.add_argument('--screening-report',type=Path)
    p.add_argument('--save-preview',type=Path);p.add_argument('--run',action='store_true');p.add_argument('--run-from-preview',type=Path)
    p.add_argument('--export',type=Path,default=Path('/tmp/daily-finance-v48-review.zip'));a=p.parse_args()
    if any(x.is_symlink() for x in (a.project,*a.project.parents)):raise ValueError('edition_input_resume_path_invalid')
    sys.path.insert(0,str(a.project/'backend'))
    from app import edition_once as entry
    from app.services import edition_input_resume as resume,edition_pipeline as core
    from app.services.edition_agenda_resume import regular
    from app.services.research_hub import save_json
    config=entry.accepted_config(json.loads(regular(a.prices).read_text()),'1')
    directory=core.ROOT/'manual-v45-fix1/edition-e0112bd1261b43b2b501c97558f8f8ba/agenda-continuation-v46'
    async def work():
        fingerprint=None
        if a.run:
            if not a.run_from_preview:p.error('--run requires --run-from-preview')
            plan=json.loads(regular(a.run_from_preview).read_text())
            from datetime import datetime
            from app.services.time_context import china_now
            if (plan.get('mode')!='saved_bodies_input_capacity_preview' or not plan.get('ready_to_run')
                    or not datetime.fromisoformat(plan['prepared_at'])<=china_now()<=datetime.fromisoformat(plan['expires_at'])):
                raise ValueError('edition_input_resume_preview_expired_or_blocked')
            fingerprint=plan['input_sha256']
        state,path,reused=await resume.continue_once(config,directory,run=a.run,input_sha=fingerprint)
        if path is None:
            if a.screening_report:
                if any(x.is_symlink() for x in (a.screening_report,*a.screening_report.parents)):raise ValueError('edition_input_resume_path_invalid')
                from app.services.edition_evidence_view import report
                original,_,_,_=resume.saved(directory)
                a.screening_report.write_text(report(original['sources']),encoding='utf-8')
                state['screening_report']=str(a.screening_report)
            if a.save_preview:
                if any(x.is_symlink() for x in (a.save_preview,*a.save_preview.parents)):raise ValueError('edition_input_resume_path_invalid')
                save_json(a.save_preview,state)
            print(json.dumps(state,ensure_ascii=False,indent=2));return
        result=entry.summary(state,path);result['existing_result_reused_no_new_requests']=reused
        result['review_zip']=str(entry.export_review(path,a.export));print(json.dumps(result,ensure_ascii=False,indent=2))
    asyncio.run(work())


if __name__=='__main__':main()
