"""Host Controller."""
import logging
import os
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

from secsgem.common import DeviceType
from secsgem.gem import GemHostHandler
from secsgem.hsms import HsmsSettings, HsmsConnectMode

from equipment_cyg.controller.help_functions import create_log_dir, LOG_FORMAT


class HostController(GemHostHandler):
    """Host controller class."""

    def __init__(self):

        hsms_settings = HsmsSettings(
            address="127.0.0.1",
            port=5000,
            connect_mode=getattr(HsmsConnectMode, "ACTIVE"),
            device_type=DeviceType.HOST
        )
        super().__init__(settings=hsms_settings)

        self._file_handler = None  # 保存日志的处理器
        self._initial_log_config()

    def _initial_log_config(self) -> None:
        """保存所有通讯日志."""
        create_log_dir()
        self.logger.addHandler(self.file_handler)
        self.protocol.communication_logger.addHandler(self.file_handler)  # secs 通讯日志

    @property
    def file_handler(self) -> TimedRotatingFileHandler:
        """设置保存日志的处理器, 每个一天自动生成一个日志文件.

        Returns:
            TimedRotatingFileHandler: 返回 TimedRotatingFileHandler 日志处理器.
        """
        if self._file_handler is None:
            logging.basicConfig(level=logging.INFO, encoding="UTF-8", format=LOG_FORMAT)
            log_file_name = f"{os.getcwd()}/log/{datetime.now().strftime('%Y-%m-%d')}"
            self._file_handler = TimedRotatingFileHandler(
                log_file_name, when="D", interval=1, backupCount=10, encoding="UTF-8"
            )
            self._file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        return self._file_handler

    def host_enable(self):
        """启动host."""
        self.enable()
        self.logger.info("*** Host 已启动 *** -> 可以连接设备MES.")
