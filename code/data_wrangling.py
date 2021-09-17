import logging
from io import BytesIO

import requests
import datetime as dt
import pandas as pd
import re
from typing import Optional
from bs4 import BeautifulSoup

# Local File. Once data exists, we don't want to re-read it.
# TODO: Put file name in config file.


LOCAL_DATA_FILENAME = 'data/full_data.pkl'
LOCAL_DATA_TEXT_FILENAME = 'data/text_data.pkl'
LOCAL_DATA_CSV_FILENAME = 'data/csv_data.pkl'

# The MnDOT web site adjusted how traffic data was maintained around 2017. Prior to 2017, all data was kept in
# individual text files. There was one file per station per year. After the update, there were csv files with one file
# per year. That file held information on all stations for the year. These need to be processed separately.

# Earliest year tracked.
FIRST_YEAR_DEFAULT = 2002
# Year where change was made.
SPLIT_YEAR = 2017

# The old text files containing volume counts are still available from the MnDOT website, but the old index
# page is no longer accessible. An archived index page is available on the WaybackMachine, located at
# https://web.archive.org/web/20181117175447/http://www.dot.state.mn.us:80/traffic/data/reports-hrvol-atr.html
# Rather than dynamically reading that page, we extracted the stations maintained in the index and list those in a
# constant list. Not all stations have entries for all years, so that needs to be handled in the read routine.
STATION_LIST = [8, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 38, 39, 40, 41, 42, 43, 44, 45, 46, 48, 49, 51, 53, 54,
                55, 56, 57, 101, 102, 103, 110, 164, 170, 172, 175, 179, 187, 188, 191, 195, 197, 198, 199, 200, 204,
                208, 209, 210, 211, 212, 213, 214, 218, 219, 220, 221, 222, 223, 225, 227, 228, 229, 230, 231, 232, 233,
                301, 303, 305, 309, 315, 321, 326, 329, 335, 336, 341, 342, 351, 352, 353, 354, 359, 365, 381, 382, 384,
                386, 388, 389, 390, 400, 402, 405, 407, 410, 420, 422, 425, 458, 460, 464]

# The files themselves are named https://www.dot.state.mn.us/traffic/data/reports/atr/Hourly_Volume/YYYY/ATRxxx.txt
# where YYYY is the four-digit year (between 2002 and 2017) and xxx is the station id number (left-padded with 0 if the
# id has fewer than three digits.) If the year is 2010 or earlier, the file suffix must be capitalized (".TXT" instead
# of ".txt")
SUFFIX_CHANGE_YEAR = 2010

TEXT_URL_STEM = f'https://www.dot.state.mn.us/traffic/data/reports/atr/Hourly_Volume/'
TEXT_URL_OLD_SUFFIX = f'.TXT'
TEXT_URL_NEW_SUFFIX = f'.txt'

# Road lanes are tracked by direction. This is either by string or by numeric value.
# Generally, directions are the four cardinal directions, but part of one month of one station uses the directions
# "northeast" and "southwest" rather than "east" and "west". Contextual clues indicate that "northeast" is equivalent
# to "east" and "southwest" to "west".
DIRECTIONS = {'North': 1, 'East': 3, 'South': 5, 'West': 7, 'Northeast': 3, 'Southwest': 7}

# The text files need to be parsed. This can be done using regular expressions. Each page of the text reports
# contains a header line indicating the station number, the direction, and the month. The station number and month
# are redundant, but the direction is needed, as it provides state for the data on the page.
TEXT_PAGE_HEADER_PATTERN = re.compile(r'Station\s*(\d+)\,\s*Direction\s*(\w+)')

# Within the page, the data lines will start with a date, although there may be a star before the line. If the star is
# present, it means that some or all of the data in the row is an estimate.
# Each row is a single date.
# Outside of the star, each data row begins with the date, in format MMM dd, yyyy dddd (MMM is abbreviated month, e.g.,
# Jan; dddd is the full day of the week
TEXT_PAGE_ROW_PATTERN = re.compile(r'^(\**)\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)')
# After the row header (date), there are 24 integers, corresponding to hours of the day ending at 1am, 2am, ..., 11pm,
# 12 mid, then a total for the row.
TEXT_PAGE_DATA_PATTERN = re.compile(r'\d+')
# The names and order of columns are meant to match with those in the more recent (2017-present) csv files. We hardcode
# this.
TEXT_PAGE_COLUMNS = ['station_id', 'dir_of_travel', 'lane_of_travel', 'date'] + list(map(str, range(1, 25)))


def get_data(conf: dict) -> Optional[pd.DataFrame]:
    # TODO: Add config option to allow obtaining files from web even if currently present.
    # TODO: As mentioned with file name definitions, move local file names to configs

    # Multiple step-process to check if local data exists or not.
    # Step 1. Check to see if we've got a complete local set. If so, read it and return at this point.
    df = read_local_data(LOCAL_DATA_FILENAME)
    if df is not None:
        return df

    # Step 2a. Check to see if we've got a complete local set of text and or csv files. If so, we can get away with only
    # grabbing the missing half and go from there.
    text_df = read_local_data(LOCAL_DATA_TEXT_FILENAME)
    csv_df = read_local_data(LOCAL_DATA_CSV_FILENAME)

    # Step 2b. If either text_df or csv_df is missing, create and save it.
    if text_df is None:
        text_df = get_text_data(conf)
        if text_df is not None:
            text_df.to_pickle(LOCAL_DATA_TEXT_FILENAME)
    if csv_df is None:
        csv_df = get_csv_data(conf)
        if csv_df is not None:
            csv_df.to_pickle(LOCAL_DATA_CSV_FILENAME)

    # Step 3. After Steps 2a and 2b, there should be a full set of local files, and text_df and csv_df should be
    # present. Combine them into a single data frame, save it, and return it.
    if text_df is not None and csv_df is not None:
        # This shouldn't be necessary, but better safe then sorry.
        df = pd.concat([text_df, csv_df])
        df.to_pickle(LOCAL_DATA_FILENAME)
        return df

    # At this point, we know something's wrong. Indicate what and return None
    if text_df is None:
        logging.error(f'text_df was not properly created')
    if csv_df is None:
        logging.error(f'csv_df was not properly created')

    return None


def read_local_data(filename: str) -> Optional[pd.DataFrame]:
    try:
        logging.info(f'Attempting to read {filename}')
        df = pd.read_pickle(filename)
        return df
    except IOError:
        logging.info(f'Cannot read {filename}')

    return None


def get_text_data(conf: dict) -> Optional[pd.DataFrame]:
    # We were unable to read the earlier data locally, so we read it from the web.
    # First, use the config to determine which years to read.
    first_year, last_year = get_years(conf, True)
    dfs = []
    for current_year in range(first_year, last_year + 1):
        logging.info(f'Obtaining year {current_year}')
        year_df = get_text_data_year(current_year)
        if year_df is not None:
            dfs.append(year_df)

    if len(dfs) > 0:
        df = pd.concat(dfs)
        return df
    else:
        return None


def get_text_data_year(current_year: int) -> Optional[pd.DataFrame]:
    dfs = []
    for station_number in STATION_LIST:
        station_df = get_text_data_year_station(current_year, station_number)
        if station_df is not None:
            dfs.append(station_df)

    if len(dfs) > 0:
        df = pd.concat(dfs)
        return df
    else:
        return None


def get_text_data_year_station(current_year: int, station_number: int) -> Optional[pd.DataFrame]:
    logging.info(f'Obtaining station {station_number} (year {current_year})')
    url = get_station_url(current_year, station_number)

    try:
        response = requests.get(url)
        response.raise_for_status()
    except (Exception,):
        logging.info(f'Response {response.status_code} reading {url}')
        return None

    df = process_text_response(current_year, station_number, response)
    return df


def process_text_response(current_year, station_number, response) -> Optional[pd.DataFrame]:
    count_data = {}
    # Process the file line-by-line
    for line in response.iter_lines():
        # Without decoding the line, regex searches will raise an error
        line = line.decode('utf-8')

        # Check to see if it's a header line.
        # TODO: Refactor to pull header line, data lines into separate functions.
        if header_line := TEXT_PAGE_HEADER_PATTERN.search(line):
            # Station ID files may contain information about a different station. In this case, correct the station
            # number and continue.
            try:
                # TODO: Magic number here.
                asserted_station = int(header_line.group(1))
                assert station_number == asserted_station
            except AssertionError:
                # Since the station number is wrong, fix it.
                logging.warning(f'Station number {station_number} corrected to {asserted_station} for '
                                f'year {current_year}')
                station_number = asserted_station

            # Header lines contain the direction. We move to extract this and continue.
            # TODO: Magic number here.
            direction_str = header_line.group(2)
            # Convert case for direction to guard against possibility that capitalization of directions changes
            # between files.
            # TODO: Magic number here. (Set a default instead)
            direction = DIRECTIONS.get(direction_str.title(), 0)

            # We have the direction, we know this isn't a data line, so jump to next line
            continue

        # Now, determine if it's a data line. We do this by checking for a date.
        if data_row := TEXT_PAGE_ROW_PATTERN.search(line):
            # data_row will match any * at the beginning as well as the month abbreviation. data_match will match any
            # numbers. The first two matched numbers will be the day and year, so these are combined with the second
            # row match group to get the date.
            data_match = TEXT_PAGE_DATA_PATTERN.findall(line)
            # TODO: Magic number here.
            date_list = [data_row.group(2)] + data_match[:2]
            date_str = ' '.join(date_list)
            date = dt.datetime.strptime(date_str, '%b %d %Y')

            # Now that we have the date, it's time to get the counts. The remaining numeric data are the hourly
            # counts and the daily count. Only the hourly counts are needed, but the daily count is used as a check.
            # TODO: Magic number here.
            hourly_list = data_match[2:-1]

            # If we don't have 24 hourly counts, something's wrong. Just ignore the line.
            try:
                assert len(hourly_list) == 24
            except AssertionError:
                logging.error(f'Hour count mismatch for station number {station_number} (direction {direction}, '
                              f'date {date}. Skipping date.')
                continue

            hourly_counts = list(map(int, hourly_list))
            daily_total = int(data_match[-1])

            try:
                assert sum(hourly_counts) == daily_total
            except AssertionError:
                logging.warning(f'Daily total mismatch for station number {station_number} (direction {direction}, '
                                f'date {date}')
                pass

            # Combine the station id and direction value with the counts in a single list to add into a dictionary keyed
            # by the column headers
            # This will be a single row of a data frame.
            # The 0 is for lane of travel, which is present in newer csv files, but not in these older text outputs.
            # The coding as 0 matches the csv files without lane info.
            data_list = [station_number, direction, 0, date] + hourly_counts
            count_data[len(count_data)] = dict(zip(TEXT_PAGE_COLUMNS, data_list))

    df = pd.DataFrame(count_data).T
    return df


def get_station_url(current_year: int, station_number: int) -> str:
    url_suffix = get_station_url_suffix(current_year)

    url = f'{TEXT_URL_STEM}{current_year}/ATR{station_number:0>3d}{url_suffix}'
    return url


def get_station_url_suffix(current_year: int) -> str:
    if current_year <= SUFFIX_CHANGE_YEAR:
        return TEXT_URL_OLD_SUFFIX
    else:
        return TEXT_URL_NEW_SUFFIX

# TODO: Badly in need of refactoring, since this is virtually identical to get_text_data except for False argument in
#  get_years and changing get_text_data_year to get_csv_data_year
def get_csv_data(conf: dict) -> Optional[pd.DataFrame]:
    urls = extract_csv_urls(conf)
    # We were unable to read the earlier data locally, so we read it from the web.
    # First, use the config to determine which years to read.
    first_year, last_year = get_years(conf, False)
    dfs = []
    for current_year in range(first_year, last_year + 1):
        logging.info(f'Obtaining year {current_year}')
        try:
            url = urls.get(current_year)
        except:
            logging.warning(f'No csv file found for {current_year}')
            continue

        year_df = get_csv_data_year(url)
        if year_df is not None:
            dfs.append(year_df)

    if len(dfs) > 0:
        df = pd.concat(dfs)
        return df
    else:
        return None


def extract_csv_urls(conf: dict) -> dict:
    #TODO: This works, but totally needs to get cleaned up a bit.
    #TODO: Magic!
    url = 'https://www.dot.state.mn.us/traffic/data/reports-hrvol-atr.html'
    reqs = requests.get(url)
    soup = BeautifulSoup(reqs.text, 'html.parser')

    first_year, last_year = get_years(conf, False)

    urls = {}
    hyperlinks = soup.find_all('a')

    for current_year in range(first_year, last_year + 1):
        year_as_str = str(current_year)
        for link in hyperlinks:
            link_str = link.string
            if link_str is not None:
                if year_as_str in link.string:
                    # print(f'{link} // {link.string}')
                    urls[current_year] = link.get('href')

    return urls


def get_csv_data_year(url: str) -> pd.DataFrame:
    # Allow redirects
    response = requests.get(url, allow_redirects=True)
    df = pd.read_csv(BytesIO(response.content))

    return df


def get_years(conf: dict, is_before_split: bool) -> (int, int):
    # Set up defaults
    first_year_def, last_year_def = get_default_years(is_before_split)

    # Determine if years are in the config file
    # First, the 'data' section needs to be there.
    # TODO: This is a magic constant
    if conf.get('data', False):
        data_conf = conf.get('data')
        # TODO: This is a magic constant
        first_year = data_conf.get('first_year', first_year_def)
        last_year = data_conf.get('last_year', last_year_def)
    else:
        first_year = first_year_def
        last_year = last_year_def

    first_year = max(first_year, first_year_def)
    last_year = min(last_year, last_year_def)
    return first_year, last_year


def get_default_years(is_before_split: bool) -> (int, int):
    if is_before_split:
        # The split year is the first year .csv files are available. Although there are text files for that year, don't
        # allow them. Instead move a year before the split.
        return FIRST_YEAR_DEFAULT, SPLIT_YEAR - 1
    else:
        # The default end year for after the split is assumed to be the current year.
        # noinspection SpellCheckingInspection
        todays_date = dt.date.today()
        current_year = todays_date.year
        return SPLIT_YEAR, current_year


