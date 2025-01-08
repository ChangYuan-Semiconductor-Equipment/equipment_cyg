"""Host Controller."""
import json
import logging
import os
import pathlib
import time
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from typing import Optional, Union

from secsgem.common import DeviceType
from secsgem.gem import GemHostHandler
from secsgem.hsms import HsmsSettings, HsmsConnectMode

from equipment_cyg.controller.help_functions import create_log_dir, LOG_FORMAT


class HostController:
    """Host controller class."""

    def __init__(self):
        self.config = self.get_config(self.get_config_path(f"{'/'.join(self.__module__.split('.'))}.json"))
        self._create_gem_host_handler()
        self._file_handler = None  # 保存日志的处理器
        self.logger = logging.getLogger("HostController")
        self.logger.addHandler(self.file_handler)
        self._initial_log_config()
        self.host_enable()
        self.report_link_event()

    def report_link_event(self):
        """将变量和报告绑定, 将报告和事件绑定."""
        report_link_event_dict = self.get_config_value("report_link_event")
        for equipment_name, report_link_event_info in report_link_event_dict.items():
            host_handler  = self.get_host_handler_with_name(equipment_name)
            for event_id, report_info in report_link_event_info.items():
                for report_id, sv_ids in report_info.items():
                    host_handler.subscribe_collection_event(int(event_id), sv_ids, int(report_id))

    def _create_gem_host_handler(self):
        """根据配置文件创建连接设备的客户端."""
        equipment_ip_dict  = self.get_equipment_ip_dict()
        for equipment_name, secs_ip in equipment_ip_dict.items():
            setting = HsmsSettings(
                address=secs_ip,
                port=self.get_config_value(equipment_name, 5000, "equipment_port"),
                connect_mode=getattr(HsmsConnectMode, "ACTIVE"),
                device_type=DeviceType.HOST
            )
            host_handler = GemHostHandler(setting)
            setattr(self, f"setting_{equipment_name}", setting)
            setattr(self, f"host_handler_{equipment_name}", host_handler)
            setattr(host_handler.protocol, "_on_event_collection_event_received", self._on_event_collection_event_received)

    def _initial_log_config(self) -> None:
        """保存所有通讯日志."""
        create_log_dir()
        equipment_ip_dict  = self.get_equipment_ip_dict()

        for equipment_name, secs_ip in equipment_ip_dict.items():
            host_handler = getattr(self, f"host_handler_{equipment_name}")
            host_handler.logger.addHandler(self.file_handler)
            host_handler.protocol.communication_logger.addHandler(self.file_handler)  # secs 通讯日志

    # 静态通用函数
    @staticmethod
    def get_config_path(relative_path: str) -> Optional[str]:
        """获取配置文件绝对路径地址.

        Args:
            relative_path: 相对路径字符串.

        Returns:
            Optional[str]: 返回绝对路径字符串, 如果 relative_path 为空字符串返回None.
        """
        if relative_path:
            return f"{os.path.dirname(__file__)}/../../{relative_path}"
        return None

    @staticmethod
    def get_config(path: str) -> dict:
        """获取配置文件内容.

        Args:
            path: 配置文件绝对路径.

        Returns:
            dict: 配置文件数据.
        """
        with pathlib.Path(path).open(mode="r", encoding="utf-8") as f:
            conf_dict = json.load(f)
        return conf_dict

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
        """启动host连接设备的所有客户端."""
        equipment_ip_dict  = self.get_equipment_ip_dict()
        for equipment_name, secs_ip in equipment_ip_dict.items():
            host_handler = getattr(self, f"host_handler_{equipment_name}")
            host_handler.enable()
            host_handler.logger.info("*** 已启动连接设备 %s 客户端 ***", equipment_name)
        self.logger.info("*** 所有的连接设备的客户端已启动 *** -> 等待 10 秒")
        time.sleep(10)
        self.logger.info("*** 所有的连接设备的客户端已启动 *** -> 等待 10 秒结束")

    def get_config_value(self, key, default=None, parent_name=None) -> Union[str, int, dict, list, None]:
        """根据key获取配置文件里的值.

        Args:
            key(str): 获取值对应的key.
            default: 找不到值时的默认值.
            parent_name: 父级名称.

        Returns:
            Union[str, int, dict, list]: 从配置文件中获取的值.
        """
        if parent_name:
            return self.config.get(parent_name).get(key, default)
        return self.config.get(key, default)

    def get_equipment_ip_dict(self) -> dict:
        """获取设备的ip字典."""
        return self.get_config_value("equipment_ip")

    def get_host_handler_with_name(self, equipment_name: str) -> GemHostHandler:
        """根据设备名称获取连接设备客户端的handler.

        Args:
            equipment_name:

        Returns:
            GemHostHandler: 连接设备服务端的 GemHostHandler 实例.
        """
        return getattr(self, f"host_handler_{equipment_name}")


    def _on_event_collection_event_received(self, data):
        """接收到设备发来的事件进行处理."""
