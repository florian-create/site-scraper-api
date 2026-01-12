#!/usr/bin/env python3
"""
Site Scraper API for Clay integration
Deploy on Render.com
"""

from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import re
import time
from collections import deque
from datetime import datetime

app = Flask(__name__)


class SiteScraper:
    def __init__(self, base_url, max_pages=25, timeout_seconds=25):
        self.base_url = base_url.rstrip('/')
        parsed = urlparse(base_url)
        self.domain = parsed.netloc
        self.scheme = parsed.scheme or 'https'
        self.max_pages = max_pages
        self.timeout_seconds = timeout_seconds
        self.start_time = time.time()

        self.visited = set()
        self.to_visit = deque()
        self.pages = []

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        })

    def is_timeout(self):
        return (time.time() - self.start_time) > self.timeout_seconds

    def normalize_url(self, url):
        parsed = urlparse(url)
        path = parsed.path.rstrip('/') or '/'
        return f"{parsed.scheme}://{parsed.netloc}{path}"

    def is_valid_url(self, url):
        try:
            parsed = urlparse(url)
            if parsed.netloc and parsed.netloc != self.domain:
                return False
            skip_ext = ['.pdf', '.jpg', '.jpeg', '.png', '.gif', '.svg', '.ico',
                       '.css', '.js', '.xml', '.json', '.zip', '.mp3', '.mp4']
            if any(parsed.path.lower().endswith(ext) for ext in skip_ext):
                return False
            return True
        except:
            return False

    def extract_links(self, soup, current_url):
        links = set()
        for a in soup.find_all('a', href=True):
            href = a.get('href', '').strip()
            if not href or href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                continue
            if href.startswith('//'):
                href = f"{self.scheme}:{href}"
            elif href.startswith('/'):
                href = f"{self.scheme}://{self.domain}{href}"
            elif not href.startswith(('http://', 'https://')):
                href = urljoin(current_url, href)
            normalized = self.normalize_url(href)
            if self.is_valid_url(normalized):
                links.add(normalized)
        return links

    def scrape_page(self, url):
        try:
            response = self.session.get(url, timeout=10, allow_redirects=True)
            content_type = response.headers.get('Content-Type', '')
            if 'text/html' not in content_type:
                return None, set()

            response.encoding = response.apparent_encoding or 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            links = self.extract_links(soup, url)

            for el in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'noscript', 'iframe', 'svg']):
                el.decompose()

            title = soup.title.string.strip() if soup.title and soup.title.string else ''

            meta_desc = ''
            meta_tag = soup.find('meta', attrs={'name': 'description'})
            if meta_tag:
                meta_desc = meta_tag.get('content', '')

            headers = {}
            for i in range(1, 4):
                h_tags = soup.find_all(f'h{i}')
                if h_tags:
                    headers[f'h{i}'] = [h.get_text(strip=True) for h in h_tags[:10]]

            content = soup.get_text(separator=' ', strip=True)
            content = re.sub(r'\s+', ' ', content)

            return {
                'url': url,
                'title': title,
                'meta_description': meta_desc,
                'headers': headers,
                'content': content[:10000]
            }, links
        except:
            return None, set()

    def crawl(self):
        start_url = self.normalize_url(self.base_url)
        self.to_visit.append(start_url)
        self.visited.add(start_url)

        while self.to_visit and len(self.pages) < self.max_pages and not self.is_timeout():
            url = self.to_visit.popleft()
            page_data, new_links = self.scrape_page(url)

            if page_data:
                self.pages.append(page_data)

            for link in new_links:
                if link not in self.visited:
                    self.visited.add(link)
                    self.to_visit.append(link)

            time.sleep(0.2)

        return {
            'domain': self.domain,
            'url': self.base_url,
            'scraped_at': datetime.now().isoformat(),
            'pages_count': len(self.pages),
            'pages': self.pages
        }


@app.route('/')
def home():
    return jsonify({
        'service': 'Site Scraper API',
        'usage': 'GET /scrape?url=https://example.com&max_pages=25',
        'params': {
            'url': 'Website URL to scrape (required)',
            'max_pages': 'Max pages to scrape (default: 25, max: 50)'
        }
    })


@app.route('/scrape')
def scrape():
    url = request.args.get('url', '').strip()

    if not url:
        return jsonify({'error': 'Missing url parameter'}), 400

    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    try:
        max_pages = min(int(request.args.get('max_pages', 25)), 50)
    except:
        max_pages = 25

    try:
        scraper = SiteScraper(url, max_pages=max_pages, timeout_seconds=25)
        result = scraper.crawl()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/scrape/summary')
def scrape_summary():
    """Returns a condensed version for Clay - just key info"""
    url = request.args.get('url', '').strip()

    if not url:
        return jsonify({'error': 'Missing url parameter'}), 400

    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    try:
        max_pages = min(int(request.args.get('max_pages', 15)), 30)
    except:
        max_pages = 15

    try:
        scraper = SiteScraper(url, max_pages=max_pages, timeout_seconds=20)
        data = scraper.crawl()

        # Extract summary
        all_h1 = []
        all_h2 = []
        all_content = []

        for page in data['pages']:
            h = page.get('headers', {})
            all_h1.extend(h.get('h1', []))
            all_h2.extend(h.get('h2', []))
            all_content.append(page.get('content', '')[:500])

        summary = {
            'domain': data['domain'],
            'pages_scraped': data['pages_count'],
            'main_titles': list(set(all_h1))[:10],
            'subtitles': list(set(all_h2))[:15],
            'homepage_content': data['pages'][0]['content'][:2000] if data['pages'] else '',
            'all_pages_preview': ' | '.join(all_content)[:5000]
        }

        return jsonify(summary)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
