"""Free offline replay only. No paid/run option exists."""
import argparse,json,sys
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,default=Path('/var/www/finance-daily'))
    p.add_argument('--export',type=Path,default=Path('/tmp/daily-finance-v50-review.zip'));a=p.parse_args()
    if any(x.is_symlink() for x in (a.project,*a.project.parents)):raise ValueError('edition_assessment_replay_path_invalid')
    sys.path.insert(0,str(a.project/'backend'))
    from app import edition_once as entry
    from app.services import edition_pipeline as core
    from app.services.edition_assessment_replay import recover
    directory=core.ROOT/'manual-v45-fix1/edition-e0112bd1261b43b2b501c97558f8f8ba/agenda-continuation-v46/input-capacity-v48'
    with core.edition_lock(core.ROOT):
        entry.require_pause();state,child,reused=recover(directory)
        result=entry.summary(state,child)
        result.update(mode='offline_already_paid_assessment_recovery',new_model_requests=0,new_search_requests=0,
            new_public_fetch_attempts=0,new_tts_requests=0,existing_recovery_reused=reused,
            readable_file=str(child/'assessment-readable.txt'),review_zip=str(entry.export_review(child,a.export)))
        print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
