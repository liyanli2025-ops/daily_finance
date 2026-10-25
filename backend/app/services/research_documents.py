"""Bounded PDF text extraction with page provenance and process isolation."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import threading
from urllib.parse import urlsplit

import requests

PDF_HOSTS = {'pdf.dfcfw.com', 'static.cninfo.com.cn', 'www.hkexnews.hk'}
# Collection uses concurrent network workers; CPU-heavy parsing shares one slot.
# This bounds the sum of parser memory and avoids competing for a small VM's CPU.
_parser_slot = threading.BoundedSemaphore(1)


def pdf_ready():
    return importlib.util.find_spec('pypdf') is not None


def read_pdf(url, timeout=25):
    started = time.monotonic()
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in PDF_HOSTS or parsed.username or parsed.password:
        raise ValueError('PDF地址未在公开披露源白名单内')
    if not pdf_ready():
        raise RuntimeError('pdf_dependency_missing')
    with requests.get(url, timeout=min(10, timeout), stream=True, allow_redirects=False) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError('PDF重定向或响应异常')
        data = bytearray()
        for chunk in response.iter_content(65536):
            if time.monotonic()-started>timeout:
                raise TimeoutError('pdf_download_budget_exhausted')
            data.extend(chunk)
            if len(data) > 12 * 1024 * 1024:
                raise ValueError('PDF超过12MB读取预算')
    if not data.startswith(b'%PDF'):
        raise ValueError('下载结果不是PDF')
    with tempfile.TemporaryDirectory(prefix='finance-pdf-') as folder:
        source = Path(folder)/'source.pdf'
        source.write_bytes(data)
        remaining = timeout-(time.monotonic()-started)
        if remaining <= 0 or not _parser_slot.acquire(timeout=max(0, remaining)):
            raise TimeoutError('pdf_queue_budget_exhausted')
        try:
            remaining = timeout-(time.monotonic()-started)
            if remaining <= 0:
                raise TimeoutError('pdf_parse_budget_exhausted')
            cpu_seconds = min(40, max(1, int(remaining)))
            process = subprocess.run(
                [sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), str(source), str(cpu_seconds)],
                capture_output=True, timeout=remaining, encoding='utf-8')
        except subprocess.TimeoutExpired as error:
            raise TimeoutError('pdf_parse_budget_exhausted') from error
        finally:
            _parser_slot.release()
        if process.returncode:
            # Fixed diagnostic only: never copy stderr, document text or URLs.
            raise RuntimeError('pdf_parser_exit:'+str(process.returncode))
        return json.loads(process.stdout)


def extract(path, cpu_seconds=20):
    # Linux production only; Windows does not expose resource limits.
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (768*1024*1024, 768*1024*1024))
        cpu_seconds = max(1, min(40, int(cpu_seconds)))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    except ImportError:
        pass
    from pypdf import PdfReader
    reader = PdfReader(path)
    if reader.is_encrypted:
        raise ValueError('encrypted_pdf')
    pages, count = [], len(reader.pages)
    for index, page in enumerate(reader.pages[:400]):
        content = page.get_contents()
        if content is not None and len(content.get_data()) > 8*1024*1024:
            raise ValueError('oversized_page_stream')
        text = page.extract_text(extraction_mode='layout') or ''
        pages.append(dict(page=index+1, text=text))
        if sum(len(item['text']) for item in pages) > 1_500_000:
            break
    if sum(len(item['text'].strip()) for item in pages) < 80:
        raise ValueError('no_extractable_text_requires_ocr')
    return dict(pages=pages, total_pages=count, read_pages=len(pages),
                reading_status='full_text' if len(pages)==count else 'partial',
                limitation='PDF文本提取不验证表格跨行和数值对应关系；未识别文本不能补写。')


def excerpt(document, limit=6000):
    """Keep complete page labels; explicitly mark prompt excerpts as excerpts."""
    pages = document['pages']
    keywords = ('主要财务', '经营情况', '主营业务', '核心竞争力', '风险提示', '盈利预测')
    ranked = sorted(pages, key=lambda item: (item['page'] <= 2,
                    sum(word in item['text'] for word in keywords)), reverse=True)
    selected, used = [], 0
    for page in ranked:
        if used >= limit:
            break
        remaining = limit-used
        text = page['text'][:remaining]
        selected.append((page['page'], text, len(text)<len(page['text'])))
        used += len(text)
    return '\n'.join(f'【原PDF第{number}页' + ('，页内节选' if cut else '') + f'】\n{text}'
                     for number,text,cut in sorted(selected))


if __name__ == '__main__':
    print(json.dumps(extract(sys.argv[1], int(sys.argv[2]) if len(sys.argv)>2 else 20), ensure_ascii=False))
