import logging
from newspaper import Source, utils
from newspaper.mthreading import fetch_news
import concurrent.futures
from datetime import datetime
import os
import re
from unidecode import unidecode
import sys
import traceback
from logging_handler import LoggingHandler
from config_handler import ConfigHandler


# Function to extract base_urls from the already loaded config
def get_source_urls(config):
    try:
        news_sources = config.get('news_sources', {})
        base_urls = [source['base_url'] for source in news_sources.values()]
        return base_urls
    except Exception as e:
        logging.error("Failed to get source URLs: %s", e)
        raise


def custom_excepthook(exc_type, exc_value, exc_traceback):
    if any(os.path.abspath(__file__) in frame.filename for frame in traceback.extract_tb(exc_traceback)):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)



def check_and_create_base_directory(base_directory):
    try:
        if not os.path.exists(base_directory):
            local_directory = os.path.join(os.getcwd(), 'archive', 'news')
            os.makedirs(local_directory, exist_ok=True)
            logging.warning(f"Base directory {base_directory} does not exist. Using local directory {local_directory}")
            return local_directory
        else:
            logging.info(f"Base directory {base_directory} exists.")
            return base_directory
    except Exception as e:
        logging.critical(f"Error checking or creating base directory: {e}")
        raise

def clean_filename(title, max_length=255):
    try:
        logging.debug("Cleaning filename for title: %s", title)
        title_ascii = unidecode(title)
        title_clean = re.sub(r'[<>:"/\\|?*\']', '', title_ascii)
        cleaned_title = title_clean[:max_length]
        logging.debug("Cleaned filename: %s", cleaned_title)
        return cleaned_title
    except Exception as e:
        logging.error(f"Error cleaning filename: {e}")
        return "unknown_title"

def extract_year_month_day(timestamp):
    try:
        logging.debug("Extracting year, month, and day from timestamp: %s", timestamp)
        if isinstance(timestamp, str):
            dt = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S")
        elif isinstance(timestamp, datetime):
            dt = timestamp
        else:
            raise ValueError("Unsupported timestamp format")
        year = dt.year
        month = f"{dt.month:02d}"
        day = f"{dt.day:02d}"
        logging.debug("Extracted year: %s, month: %s, day: %s", year, month, day)
        return year, month, day
    except Exception as e:
        logging.error(f"Error extracting year, month, and day: %s", e)
        return None, None, None

def create_directories(path):
    try:
        os.makedirs(path, exist_ok=True)
        logging.info(f"Directories created successfully or already exist: %s", path)
    except Exception as e:
        logging.error(f"An error occurred while creating directories: %s", e)

def save_article(article, source, base_archive_directory):
    try:
        publish_date = article.publish_date
        title = article.title
        clean_title = clean_filename(title)
        year, month, day = extract_year_month_day(publish_date)

        if year is None:
            logging.debug("Could not extract year from publish date")
            year = 0
        if month is None:
            logging.debug("Could not extract month from publish date")
            month = 0

        if day is not None:
            filename = f"{year:02}-{month:02}-{day:02} {clean_title}.json"
        else:
            filename = f"{year:02}-{month:02} {clean_title}.json"

        save_directory = os.path.join(base_archive_directory, source.brand, str(year), str(month))
        create_directories(save_directory)

        save_path = os.path.join(save_directory, filename)
        json_data = article.to_json()
        try:
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(json_data)
                logging.info(f"Article saved to %s", save_path)
        except Exception as e:
            logging.error(f"Error writing to file: %s", e)

    except Exception as e:
        logging.error(f"Failed to save article: %s", e)

class NewsCrawler:
    def __init__(self, source_urls, config=None):
        try:
            logging.info("Initializing NewsCrawler with sources: %s", source_urls)
            self.sources = []
            for url in source_urls:
                source = Source(url, config=config)
                if first_run:
                    source.clean_memo_cache()
                self.sources.append(source)
            self.articles = []
        except Exception as e:
            logging.critical(f"Error initializing NewsCrawler: %s", e)

    def build_source(self, source):
        try:
            source.build()
            logging.debug(f"Built source: {source}")
        except Exception as e:
            logging.error(f"Error building source: {e}")

    def build_sources(self, max_workers):
        try:
            logging.info("Building sources")
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(self.build_source, source): source for source in self.sources}
                for future in concurrent.futures.as_completed(futures):
                    source = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        logging.error(f"Source %s generated an exception: %s", source.url, e)
            logging.info("Sources built successfully")
        except Exception as e:
            logging.error(f"Error building sources: %s", e)

    def crawl_articles(self):
        try:
            logging.info(f"Crawling articles.")
            self.articles = fetch_news(self.sources, threads=4)
            logging.info(f"Articles crawled successfully.")
        except Exception as e:
            logging.error(f"Error crawling articles.")

    def extract_information(self):
        try:
            logging.info("Extracting information from articles")
            for source in self.sources:
                logging.debug("Processing source: %s", source.url)
                for article in source.articles:
                    try:
                        article.download()
                        article.parse()
                        article.nlp()
                        save_article(article, source, base_archive_directory)
                    except Exception as e:
                        logging.error(f"Error processing article: {e}")
        except Exception as e:
            logging.error(f"Error extracting information: %e")

if __name__ == "__main__":
    # sys.excepthook = custom_excepthook
    #TODO - batch save files to cut down on write speeds
    try:
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yml')
        config = ConfigHandler.load_config(config_path)
        LoggingHandler.setup_logging(config)

        base_archive_directory = check_and_create_base_directory(config['settings']['base_archive_dir'])
        utils.cache_disk.enabled = False
        run_once = config['settings']['run_once']
        max_workers = config['settings'].get('max_workers', 5)  # Default to 5 workers if not specified
        sources_per_batch = config['settings'].get('sources_per_batch', 2)  # Default to 10 sources per batch if not specified
        first_run = True

        while True:
            source_urls = get_source_urls(config)
            for i in range(0, len(source_urls), sources_per_batch):
                batch_urls = source_urls[i:i+sources_per_batch]
                crawler = NewsCrawler(batch_urls)
                crawler.build_sources(max_workers)
                crawler.crawl_articles()
                crawler.extract_information()
            if run_once:
                logging.info(f"Exiting program after running once.")
                break
            else:
                first_run = False
    except KeyboardInterrupt:
        logging.info("Script interrupted by user.")
    except Exception as e:
        logging.critical(f"Unexpected error in main execution: %s", e)