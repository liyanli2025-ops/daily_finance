"""Inspect up to three explicit public article URLs through the deployed reader.

Default: local plan only. --run-public enables bounded article GETs, never model,
search API, TTS, service operations or App database writes. Each URL gets a durable
attempt marker; existing failures and past attempts are not automatically retried.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from urllib.parse import urlsplit


def fingerprint(url):
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def urls_from_args(values):
    from app.services.event_observations import canonical
    from app.services.primary_discovery import landing_page, unsupported_page
    if not 1 <= len(values) <= 3:
        raise ValueError("Provide one to three public article URLs")
    urls = []
    for value in values:
        url = canonical(value)
        parts = urlsplit(url or "")
        if (not url or parts.scheme not in {"http", "https"} or not parts.hostname
                or parts.username or parts.password or parts.port not in {None, 80, 443}
                or len(url) > 2048 or landing_page(url) or unsupported_page(url)):
            raise ValueError("An input is not a supported public article URL")
        if url not in urls:
            urls.append(url)
    return urls


@contextmanager
def count_fetches(reader, counter):
    original = reader.fetch_html_once

    def counted(url, deadline=None):
        if counter["public_fetch_attempts"] >= 9:
            raise ValueError("public_read_budget_exhausted")
        counter["public_fetch_attempts"] += 1
        return original(url, deadline)

    reader.fetch_html_once = counted
    try:
        yield
    finally:
        reader.fetch_html_once = original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path("/var/www/finance-daily"))
    parser.add_argument("--url", action="append", required=True)
    parser.add_argument("--run-public", action="store_true")
    args = parser.parse_args()
    backend = args.project.absolute() / "backend"
    if not (backend / "app/config.py").is_file():
        parser.error("Project backend not found")
    sys.path.insert(0, str(backend))
    from app.services import web_research as reader
    from app.services.generic_extraction import runtime_status
    from app.services.research_hub import ROOT, save_json
    from app.services.source_health import ensure_active, PAUSED_PUBLIC_ARTICLES, RetiredSourceError
    urls = urls_from_args(args.url)
    markers = backend / "data/diagnostics/public-reading-check-v1"
    targets = []
    for url in urls:
        reason = None
        if (markers / (fingerprint(url) + ".json")).exists():
            reason = "previous_attempt_no_automatic_retest"
        elif url in PAUSED_PUBLIC_ARTICLES:
            reason = "article_paused_no_auto_retest"
        else:
            try:
                ensure_active(ROOT, "research-public-url:" + url)
            except RetiredSourceError:
                reason = "article_paused_no_auto_retest"
        targets.append(dict(url=url, skip_reason=reason))
    plan = dict(mode="public_reading_preview", targets=targets, extractor=runtime_status(),
                max_url_reads=3, max_public_fetch_attempts_including_redirects=9,
                max_seconds=60, window_hours=72,
                public_fetch_attempts=0, model_requests=0, search_requests=0, tts_requests=0,
                limitation="显式链接的读取检查；不是模型自主找新闻、覆盖充分或内容质量验收。")
    if not args.run_public or not any(not row["skip_reason"] for row in targets):
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    flag = backend / "data/.automation-paused"
    if not flag.is_file() or flag.is_symlink():
        raise RuntimeError("Existing maintenance pause is required")
    if not plan["extractor"]["ready"]:
        raise RuntimeError("Extractor is not ready; no public request made")
    from app.services.episode_workspace import EpisodeWorkspace
    from app.services.reading_acceptance import replay, render_review
    from app.services.time_context import china_now
    # Use the actual new cutoff; do not backdate it to make an old URL pass.
    workspace = EpisodeWorkspace([], now=china_now())
    output = workspace.path / "public-reading-check.json"
    counter = dict(public_fetch_attempts=0)
    state = dict(mode="public_reading_check", status="running", plan=plan,
                 workspace=str(workspace.path), rows=[], model_requests=0,
                 search_requests=0, tts_requests=0, counter=counter)
    save_json(output, state)
    markers.mkdir(parents=True, exist_ok=True, mode=0o700)
    deadline = time.monotonic() + 60
    try:
        with count_fetches(reader, counter):
            for target in targets:
                url = target["url"]
                if target["skip_reason"]:
                    state["rows"].append(dict(url=url, status="skipped", reason=target["skip_reason"]))
                    continue
                if time.monotonic() >= deadline or not flag.is_file():
                    state["status"] = "stopped_time_or_pause_changed"
                    break
                marker = markers / (fingerprint(url) + ".json")
                try:
                    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    state["rows"].append(dict(url=url, status="skipped", reason="concurrent_or_previous_attempt"))
                    continue
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(dict(url=url, workspace=str(workspace.path),
                                   started_at=china_now().isoformat()), stream)
                before = counter["public_fetch_attempts"]
                response = reader.read_public(workspace, url, hours=72,
                    deadline=min(deadline, time.monotonic() + 20), characters=1800)
                material = response.get("material", {})
                item = workspace.documents.get(material.get("id"))
                state["rows"].append(dict(url=url, status=response.get("status"),
                    reason=response.get("reason"), title=getattr(item, "title", None),
                    stored_body_characters=len(item.content) if item is not None else 0,
                    public_fetch_attempts=counter["public_fetch_attempts"] - before,
                    reused_from=response.get("reused_from"),
                    response_capture=response.get("response_capture"),
                    generic_extractor_used=("正文算法：trafilatura" in item.market_impact
                                            if item is not None and item.market_impact else None)))
                save_json(output, state)
        captures = workspace.path / "public-responses"
        if captures.is_dir():
            review = replay(captures, hours=72)
            folder = Path(tempfile.mkdtemp(prefix="reading-review-", dir=captures))
            save_json(folder / "result.json", review)
            fd = os.open(folder / "review.md", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(render_review(review))
            state.update(review_directory=str(folder), replay_counts=review["counts"],
                         replay_reasons=review["reasons"])
        state["status"] = "completed_pending_human_review" if state["status"] == "running" else state["status"]
    except Exception as error:
        state.update(status="failed_no_automatic_retest", error_type=type(error).__name__,
                     error_code=reader.failure_reason(error))
    finally:
        state.update(result_file=str(output), pause_preserved=flag.is_file(),
                     real_collection_accepted=False, content_accepted=False,
                     limitation="只验证显式链接读取；保存全文不代表模型读完，算法非完整性或事实保证。")
        save_json(output, state)
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0 if (state["status"] == "completed_pending_human_review"
                 and any(row.get("status") == "ok" for row in state["rows"])) else 2


if __name__ == "__main__":
    raise SystemExit(main())
