from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

HOSTNAME = "127.0.0.1"
PORT = "3306"
DATABASE = "cyg"
USERNAME = "root"
PASSWORD = "liuwei.520"
DB_URI = f"mysql+pymysql://{USERNAME}:{PASSWORD}@{HOSTNAME}:{PORT}/{DATABASE}?charset=utf8mb4"
SQLALCHEMY_DATABASE_URI = DB_URI
MAX_CONNECTIONS = 10

MYSQL_SETTINGS = {
    "host": HOSTNAME,
    "port": 3306,
    "user": USERNAME,
    "passwd": PASSWORD
}


def get_declarative_base():
    return declarative_base()


ENGINE = create_engine(DB_URI)
SESSION_CLASS = sessionmaker(bind=ENGINE)
