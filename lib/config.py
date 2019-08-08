import configparser


config = configparser.ConfigParser()
with open('config.ini') as fp:
    config.read_file(fp)
