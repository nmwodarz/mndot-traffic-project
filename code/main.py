from data_wrangling import get_data


def main():
    conf = read_config()

    should_get_data = True
    should_log = True

    if should_get_data:
        get_data()
    if should_log:
        set_logging()

def read_config() --> dict:
    ...

def set_logging():
    pass

if __name__ == '__main__':
    main()
