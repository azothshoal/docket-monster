from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import logging
import os
import re
import time
import random
from datetime import datetime, timedelta
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OUTPUT_DIR = "judge_txt_pages"
MAIN_PAGE_FALLBACK = "judges.html"

class CalendarTextScraper:
    def __init__(self):
        load_dotenv()

        self.base_url = "https://www.cand.uscourts.gov"
        self.calendar_list_url = 'https://www.cand.uscourts.gov/calendars/judges-weekly-calendars/'
        self.judges_data = []

        today = datetime.now()
        self.next_week_start = today + timedelta(days=(7 - today.weekday()))
        self.next_week_end = self.next_week_start + timedelta(days=6)
        logger.info(f"Filtering for dates between {self.next_week_start.date()} and {self.next_week_end.date()}")

        os.makedirs(OUTPUT_DIR, exist_ok=True)

    def get_html_content(self, url):
        try:
            time.sleep(random.uniform(1, 3))
            logger.info(f"Fetching content from {url}")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False, slow_mo=50)
                context = browser.new_context()
                page = context.new_page()
                page.goto(url, timeout=60000, wait_until="commit")
                time.sleep(5)
                content = page.content()
                browser.close()
                return content
        except Exception as e:
            logger.error(f"Error fetching content from {url}: {e}")
            return None

    def _parse_judges_list(self, html_content):
        if not html_content:
            return []

        soup = BeautifulSoup(html_content, 'html.parser')
        judges = []

        rows = soup.find_all('tr')
        for row in rows:
            cells = row.find_all('td')
            if len(cells) != 2:
                continue

            link = cells[0].find('a', href=True)
            location = cells[1].get_text(strip=True)

            if link and link.get('href') and link.get_text(strip=True):
                href = link['href']
                name = link.get_text(strip=True)

                judges.append({
                    'name': name,
                    'url': href if href.startswith('http') else f"https://cand.uscourts.gov{href}",
                    'location': location
                })

        return judges

    def scrape_and_save_text(self):
        main_page = self.get_html_content(self.calendar_list_url)

        if main_page:
            with open(MAIN_PAGE_FALLBACK, "w", encoding="utf-8") as f:
                f.write(main_page)
                logger.info(f"Saved main page to {MAIN_PAGE_FALLBACK} for fallback use")
        else:
            logger.warning(f"Falling back to local HTML file: {MAIN_PAGE_FALLBACK}")
            try:
                with open(MAIN_PAGE_FALLBACK, "r", encoding="utf-8") as f:
                    main_page = f.read()
            except FileNotFoundError:
                logger.error(f"Fallback file {MAIN_PAGE_FALLBACK} not found. Cannot proceed.")
                return

        judges = self._parse_judges_list(main_page)
        logger.info(f"Found {len(judges)} judges")

        for judge in judges:
            try:
                logger.info(f"Fetching calendar for {judge['name']}")
                html = self.get_html_content(judge['url'])
                if not html:
                    continue

                soup = BeautifulSoup(html, 'html.parser')
                page_text = soup.get_text(separator='\n', strip=True)

                filename = re.sub(r'[^a-zA-Z0-9]', '_', judge['name']) + ".txt"
                filepath = os.path.join(OUTPUT_DIR, filename)

                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(f"Judge: {judge['name']}\n")
                    f.write(f"Location: {judge['location']}\n")
                    f.write(f"Next week: {self.next_week_start.date()} to {self.next_week_end.date()}\n")
                    f.write("\n---\n\n")
                    f.write(page_text)

                logger.info(f"Saved calendar to {filepath}")
            except Exception as e:
                logger.error(f"Failed to save calendar for {judge['name']}: {e}")
                continue

if __name__ == "__main__":
    scraper = CalendarTextScraper()
    scraper.scrape_and_save_text()