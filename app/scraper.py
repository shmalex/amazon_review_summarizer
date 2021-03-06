'''
This script contains functions that scrapes an Amazon product page, stores
HTML files offline, stores review data into mongodb, and creates Loader objects
for use with the SentCustomProperties class of functions in parsers.py
'''

from bs4 import BeautifulSoup
from pymongo import MongoClient
import math
import os
import re
import time


class Loader(object):
    '''
    Class for scraping a review site on Amazon. Stores html files locally
    and scrapes off the stored files.
    '''
    def __init__(self, url=None, name=None):
        '''
        INPUT: str, str
        OUTPUT: None

        Attributes:
            authors (list): list of strings or review authors
            asin (str): asin identifier for Amazon product
            headlines (list): list of strings of review headlines
            name (str): custom name for Amazon product
            ratings (list): list of ints of review ratings
            reviews (list): list of strings of review text
            url (str): url of the amazon link to scrape (required for scraping)
        '''
        self.asin = None
        self.name = name
        self.ratings = None
        self.reviews = None
        self.url = url

    def _get_id(self, url):
        '''
        INPUT: str
        OUTPUT: None

        Args:
            url: an Amazon url string

        Gets asin identifer for amazon product from a url
        '''

        # url format: https://www.amazon.com/.../.../id/...
        regex = re.compile(r'(?<=/)[^/]*')
        asin = regex.findall(url)[-2]

        if len(asin) != 10:
            # url format https://www.amazon.com/.../id
            asin = regex.findall(url)[-1][:10]

        self.asin = asin

    def _delete(self):
        '''
        Deletes folder with preexisting review html data for asin
        '''
        path = os.getcwd() + '/reviews/com/{}/'.format(self.asin)
        pages = [file_ for file_ in os.listdir(path)]

        try:
            for page in pages:
                os.remove(path + page)
        except:
            print 'No files to delete!'

        try:
            os.rmdir(path)
        except:
            print 'No folder to delete!'

    def _get_html_count(self, folder):
        '''
        INPUT: str
        OUTPUT: int

        Args:
            folder: path of folder to check count of html files

        Returns a count of the number of html files inside specified folder
        '''
        return len([htm for htm in os.listdir(folder) if htm[-4:] == 'html'])

    def scrape(self, n_reviews=300, delete=False, retries=0):
        '''
        INPUT: int, bool, int
        OUTPUT: None

        Args:
            n_reviews: number of reviews to scrape
            delete: option to force delete folder containing cached reviews
            retries: current count of scraper function retries

        Scrapes n most helpful amazon reviews and extracts reviews.
        If already scraped, extracts reviews.
        '''
        try:
            self._get_id(self.url)
        except:
            raise RuntimeError("Cannot find asin from the url.")

        folder = os.getcwd() + '/reviews/com/' + self.asin

        if delete:
            self._delete()

        if 'amazon_crawler.py' in os.listdir(os.getcwd()):
            cmd = 'python amazon_crawler.py'
        elif 'amazon_crawler.py' in os.listdir(os.getcwd() + '/scripts'):
            cmd = 'python scripts/amazon_crawler.py'
        else:
            raise RuntimeError("Put amazon_crawler.py in same folder as "
                               "current working directory or inside scripts"
                               "folder.")

        if not os.path.isdir(folder):
            # Run Amazon scraper
            # Credit to Andrea Esuli
            # https://github.com/aesuli/amadown2py
            try:
                os.system('{} -d com {} -m {} -o reviews'
                          .format(cmd, self.asin, n_reviews))
                last_page = self._get_html_count(folder)
            except NameError:
                raise RuntimeError("Invalid ASIN")
        else:
            # Check to see if number of html files is sufficient
            new_files = True
            rev_cnt_tag = "a-size-medium totalReviewCount"

            with open('{}/{}_1.html'.format(folder, self.asin), 'r') as f:
                soup = BeautifulSoup(f, 'html.parser')

            tag = soup.find("span", {"class": rev_cnt_tag})
            reviews = int(tag.text.replace(',', ''))
            expected_pages = min(int(math.ceil(n_reviews / 10.)),
                                 int(math.ceil(reviews / 10.)))

            last_page = self._get_html_count(folder)

            while last_page != expected_pages and new_files:
                # Wait for background scraping to complete
                time.sleep(10)
                old_count = last_page
                last_page = self._get_html_count(folder)

                if old_count == last_page:
                    # No background scraping
                    new_files = False

            if last_page != expected_pages and not new_files:
                # Not enough files, delete files and force rescrape in the
                # next while loop
                last_page = 1

        if retries > 0:
            return retries, last_page

        while last_page == 1 and retries < 5:
            retries += 1
            retries, last_page = self.scrape(n_reviews, delete=True,
                                             retries=retries)

        if last_page == 1 and retries == 5:
            self._delete()
            raise RuntimeError("Scraping Failed!")

    def extract(self, asin=None):
        '''
        INPUT: str
        OUTPUT: None

        Args:
            asin: asin identifier for Amazon product (only input as argument
                  if scraping is done seperately from extraction)

        Extracts the star rating, review text, author name, and review headline
        from directory of amazon html files and stores to MongoDB. Full lists
        of rating and review data are stored as lists in the Loader object.
        '''
        client = MongoClient()
        db = client['ars']
        tab = db['review_data']
        index = 0

        if asin:
            self.asin = asin

        if not self.name:
            f = os.getcwd() + '/reviews/com/{0}/{0}_1.html'.format(self.asin)

            with open(f, 'r') as html:
                soup = BeautifulSoup(html, 'html.parser')

            try:
                self.name = soup.select('.a-link-normal')[0].text
            except:
                raise RuntimeError("Invalid HTML code")

        path = os.getcwd() + '/reviews/com/{}/'.format(self.asin)
        pages = [file_ for file_ in os.listdir(path) if file_[-5:] == '.html']
        ratings, reviews = [], []

        for page in pages:
            with open(path + page, 'r') as f:
                soup = BeautifulSoup(f, 'html.parser')
                tags = soup.findAll("div", {"class": "a-section review"})

                if not tags:
                    print '{} is an invalid page format for scraping' \
                        .format(page)
                    continue

                for tag in tags:
                    _id = "{}_{}".format(self.asin, index)
                    r_class = "a-size-base review-text"
                    a_class = "a-size-base a-link-normal author"
                    h_class = "a-size-base a-link-normal review-title " \
                        "a-color-base a-text-bold"

                    rating = int(tag.find('i').text[0])
                    review = tag.findAll("span", {"class": r_class})[0].text

                    try:
                        author = tag.findAll("a", {"class": a_class})[0].text
                    except:
                        author = "Anonymous"
                    try:
                        headline = tag.findAll("a", {"class": h_class})[0].text
                    except:
                        headline = "No headline"

                    ratings.append(rating)
                    reviews.append(review)

                    data = {'asin': self.asin, 'review_idx': index,
                            'rating': rating, 'review': review,
                            'author': author, 'headline': headline}

                    tab.update_one({'_id': _id}, {'$set': data},
                                   upsert=True)

                    index += 1

        self.ratings, self.reviews = ratings, reviews
        return self
