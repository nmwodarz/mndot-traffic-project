from datetime import datetime
import logging
from typing import Optional

from data_wrangling import get_data
import yaml


def main():
    conf = read_config()

    set_logging(conf)
    df = get_data(conf)

    # should_get_data = True
    # should_log = True
    #
    # if should_get_data:
    #     get_data()
    # if should_log:
    #     set_logging()


def read_config() -> dict:
    """
    Reads configuration from yaml file config.yml

    :rtype: dict
    """
    # TODO: This is a magic constant
    with open("config.yml", "r") as stream:
        try:
            return yaml.safe_load(stream)
        except yaml.YAMLError as e:
            print(e)
            raise e


def set_logging(conf: dict):
    # Provide an empty dict if the key is missing so that the .get methods called later don't fail.
    log_conf = conf.get('logging', {})

    level = get_logger_level(log_conf)

    # While it might be nice to have a configurable filename, it's not currently worth the time investment to figure
    # out how to make time-dependent filenames happen through the config file.
    now = datetime.now()
    filename_date = now.strftime('%Y_%m_%d_(%H_%M_%S)')
    filename = f'logs/log_{filename_date}.txt'

    # We do allow for changing format strings.
    # TODO: This is a magic constant
    format = log_conf.get('format', f'%(levelname)s: (%(asctime)s) %(message)s')
    datefmt = log_conf.get('datefmt', f'%m/%d/%Y %H:%M:%S')

    logging.basicConfig(filename=filename,
                        filemode='w',
                        level=level,
                        format=format,
                        datefmt=datefmt)


def get_logger_level(conf: Optional[dict]) -> int:
    # Only set the logger if the 'logging' section of the config file is present.
    # TODO: This is a magic constant
    if conf.get('is_active', False):
        # TODO: This is a magic constant
        level_token = conf.get('level', 0)
        # Send string parsing off to its own function
        if type(level_token) == str:
            return parse_logger_level_string(level_token)

        # Now, check numeric values. Non-integer or negative values are interpreted as zero
        try:
            level_as_int = int(level_token)
            # The level is numeric.
            if level_token >= 0 and (level_token == level_as_int):
                return level_as_int
        except:
            # The level isn't numeric, so just return 0
            return 0

    # The fall through is to return 0
    return 0


LOGGER_LEVEL_STRINGS = {
    'CRITICAL': 50,
    'ERROR': 40,
    'WARNING': 30,
    'INFO': 20,
    'DEBUG': 10,
    'NOTSET': 0
}


def parse_logger_level_string(level_str: str) -> int:
    return LOGGER_LEVEL_STRINGS.get(level_str.upper(), 0)


if __name__ == '__main__':
    main()
