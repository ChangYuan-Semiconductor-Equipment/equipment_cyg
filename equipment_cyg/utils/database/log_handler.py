import logging

from equipment_cyg.utils.database.operations import insert_data


class DatabaseHandler(logging.Handler):
    """日志保存到数据库的处理器."""
    def __init__(self):
        super().__init__()

    def emit(self, record):
        try:
            insert_data(record.levelname, record.message)
        except Exception as e:
            print(f"Error occurred while writing to database: {e}")
