import os
import pathlib


log_format = "%(asctime)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s"


def create_log_dir():
    """判断log目录是否存在, 不存在就创建."""
    log_dir = pathlib.Path(f"{os.getcwd()}/log")
    if not log_dir.exists():
        os.mkdir(log_dir)