"""Equipment controller."""
import csv
import datetime
import functools
import json
import logging
import os
import pathlib
import subprocess
import threading
from logging.handlers import TimedRotatingFileHandler
from typing import Union, Optional

from secsgem.common import DeviceType, Message
from secsgem.gem import CollectionEvent, GemEquipmentHandler, StatusVariable, RemoteCommand, Alarm
from secsgem.secs.data_items.tiack import TIACK
from secsgem.secs.functions import SecsS02F18
from secsgem.secs.variables import U4, Array
from secsgem.hsms import HsmsSettings, HsmsConnectMode

from equipment_cyg.controller.enum_sece_data_type import EnumSecsDataType


# pylint: disable=W1203
class Controller(GemEquipmentHandler):  # pylint: disable=R0901
    """Equipment controller class."""

    def __init__(self, **kwargs):
        self.config = self.get_config(self.get_config_path(f"{'/'.join(self.__module__.split('.'))}.conf"))
        self._file_handler = None  # 保存日志的处理器

        hsms_settings = HsmsSettings(
            address=self.get_config_value("secs_ip", "127.0.0.1"),
            port=self.get_config_value("secs_port", 5000),
            connect_mode=getattr(HsmsConnectMode, self.get_config_value("connect_mode", "PASSIVE")),
            device_type=DeviceType.EQUIPMENT
        )
        super().__init__(settings=hsms_settings, **kwargs)

        self.model_name = self.config.get("model_name")
        self.software_version = self.config.get("software_version")

        self._initial_log_config()
        self._initial_evnet()
        self._initial_status_variable()
        self._initial_remote_command()
        self._initial_alarm()

    # 初始化函数
    def _initial_log_config(self) -> None:
        """保存所有 self.__module__ + "." + self.__class__.__name__ 日志和sec通讯日志."""
        self.create_log_dir()
        self.logger.addHandler(self.file_handler)  # 所有 self.__module__ + "." + self.__class__.__name__ 日志
        self.protocol.communication_logger.addHandler(self.file_handler)  # secs 通讯日志


    def _initial_evnet(self):
        """加载定义好的事件."""
        collection_events = self.config.get("collection_events", {})
        for event_name, event_info in collection_events.items():
            self.collection_events.update({
                event_name: CollectionEvent(name=event_name, data_values=[], **event_info)
            })

    def _initial_status_variable(self):
        """加载定义好的变量."""
        status_variables = self.config.get("status_variable", {})
        for sv_name, sv_info in status_variables.items():
            sv_id = sv_info.get("svid")
            value_type_str = sv_info.get("value_type")
            value_type = getattr(EnumSecsDataType, value_type_str).value
            sv_info["value_type"] = value_type
            self.status_variables.update({sv_id: StatusVariable(name=sv_name, **sv_info)})
            sv_info["value_type"] = value_type_str

    def _initial_remote_command(self):
        """加载定义好的远程命令."""
        remote_commands = self.config.get("remote_commands", {})
        for rc_name, rc_info in remote_commands.items():
            ce_id = rc_info.get("ce_id")
            self.remote_commands.update({rc_name: RemoteCommand(name=rc_name, ce_finished=ce_id, **rc_info)})

    def _initial_alarm(self):
        """加载定义好的报警."""
        if alarm_path := self.get_alarm_path():
            with pathlib.Path(alarm_path).open("r", encoding="UTF-8") as file:
                csv_reader = csv.reader(file)
                next(csv_reader)
                for row in csv_reader:
                    alarm_id, alarm_name, alarm_text, alarm_code, ce_on, ce_off, *_ = row
                    self.alarms.update({
                        alarm_id: Alarm(alarm_id, alarm_name, alarm_text, int(alarm_code), ce_on, ce_off)
                    })

    # host给设备发送指令

    # noinspection PyUnusedLocal
    def _on_s02f17(self, handler, packet) -> SecsS02F18:
        """获取设备时间.

        Returns:
            SecsS02F18: SecsS02F18 实例.
        """
        del handler, packet
        return self.stream_function(2, 18)(datetime.datetime.now().strftime("%Y%m%d%H%M%S%C"))

    # noinspection PyUnusedLocal
    def _on_s02f31(self, handler, packet):
        """设置设备时间."""
        del handler
        function = self.settings.streams_functions.decode(packet)
        parser_result = function.get()
        date_time_str = parser_result
        if len(date_time_str) not in (14, 16):
            self.logger.info(f"***设置失败*** --> 时间格式错误: {date_time_str} 不是14或16个数字！")
            return self.stream_function(2, 32)(1)
        current_time_str = datetime.datetime.now().strftime("%Y%m%d%H%M%S%C")
        self.logger.info(f"***当前时间*** --> 当前时间: {current_time_str}")
        self.logger.info(f"***设置时间*** --> 设置时间: {date_time_str}")
        status = self.set_date_time(date_time_str)
        current_time_str = datetime.datetime.now().strftime("%Y%m%d%H%M%S%C")
        if status:
            self.logger.info(f"***设置成功*** --> 当前时间: {current_time_str}")
            ti_ack = TIACK.ACK
        else:
            self.logger.info(f"***设置失败*** --> 当前时间: {current_time_str}")
            ti_ack = TIACK.TIME_SET_FAIL
        return self.stream_function(2, 32)(ti_ack)

    def _on_s07f01(self, handler, packet):
        """host发送s07f01,下载配方请求前询问,调用此函数."""
        raise NotImplementedError("如果使用,这个方法必须要根据产品重写！")

    def _on_s07f03(self, handler, packet):
        """host发送s07f03,下发配方名及主体body,调用此函数."""
        raise NotImplementedError("如果使用,这个方法必须要根据产品重写！")

    def _on_s07f05(self, handler, packet):
        """host请求配方列表"""
        raise NotImplementedError("如果使用,这个方法必须要根据产品重写！")

    def _on_s07f06(self, handler, packet):
        """host下发配方数据"""
        raise NotImplementedError("如果使用,这个方法必须要根据产品重写！")

    def _on_s07f17(self, handler, packet):
        """删除配方."""
        raise NotImplementedError("如果使用,这个方法必须要根据产品重写！")

    def _on_s07f19(self, handler, packet):
        """host请求配方列表."""
        raise NotImplementedError("如果使用,这个方法必须要根据产品重写！")

    def _on_s10f03(self, handler, packet):
        """host terminal display signal, need override."""
        raise NotImplementedError("如果使用,这个方法必须要根据产品重写！")

    # 通用函数
    def send_s6f11(self, event_name):
        """给EAP发送S6F11事件.

        Args:
            event_name (str): 事件名称.
        """

        def _ce_sender():
            reports = []
            event = self.collection_events.get(event_name)
            # noinspection PyUnresolvedReferences
            link_reports = event.link_reports
            for report_id, sv_ids in link_reports.items():
                variables = []
                for sv_id in sv_ids:
                    sv_instance: StatusVariable = self.status_variables[sv_id]
                    if issubclass(sv_instance.value_type, Array):
                        value = sv_instance.value
                        variables += value
                    else:
                        value = sv_instance.value_type(sv_instance.value)
                        variables.append(value)
                reports.append({"RPTID": U4(report_id), "V": variables})

            self.send_and_waitfor_response(
                self.stream_function(6, 11)({"DATAID": 1, "CEID": event.ceid, "RPT": reports})
            )

        threading.Thread(target=_ce_sender, daemon=True).start()

    def enable_equipment(self):
        """启动监控EAP连接的服务."""
        self.enable()  # 设备和host通讯
        self.logger.info("*** CYG SECSGEM 服务已启动 *** -> 等待工厂 EAP 连接!")

    def get_config_value(self, key, default=None) -> Union[str, int, dict, list, None]:
        """根据key获取配置文件里的值.

        Args:
            key(str): 获取值对应的key.
            default: 找不到值时的默认值.

        Returns:
            Union[str, int, dict, list]: 从配置文件中获取的值.
        """
        return self.config.get(key, default)

    def get_receive_data(self, message: Message) -> Union[dict, str]:
        """解析Host发来的数据并返回.

        Args:
            message (Message): Host发过来的数据包实例.

        Returns:
            Union[dict, str]: 解析后的数据.
        """
        function = self.settings.streams_functions.decode(message)
        return function.get()

    def get_sv_id_with_name(self, sv_name: str) -> Optional[int]:
        """根据变量名获取变量id.

        Args:
            sv_name: 变量名称.

        Returns:
            Optional[int]: 返回变量id, 没有此变量返回None.
        """
        if sv_info := self.get_config_value("status_variable").get(sv_name):
            return sv_info["svid"]
        return None

    def get_sv_value_with_name(self, sv_name: str) -> Union[int, str, bool, list, float]:
        """根据变量名获取变量值.

        Args:
            sv_name: 变量名称.

        Returns:
            Union[int, str, bool, list, float]: 返回对应变量的值.
        """
        return self.status_variables.get(self.get_sv_id_with_name(sv_name)).value

    def set_sv_value_with_name(self, sv_name: str, sv_value: Union[str, int, float, list]):
        """设置指定变量的值.

        Args:
            sv_name (str): 变量名称.
            sv_value (Union[str, int, float, list]): 要设定的值.
        """
        self.status_variables.get(self.get_sv_id_with_name(sv_name)).value = sv_value

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

    @staticmethod
    def update_config(path, data: dict):
        """更新配置文件内容.

        Args:
            path: 配置文件绝对路径.
            data: 新的配置文件数据.
        """
        with pathlib.Path(path).open(mode="w+", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    @staticmethod
    def set_date_time(modify_time_str) -> bool:
        """设置windows系统日期和时间.

        Args:
            modify_time_str (str): 要修改的时间字符串.

        Returns:
            bool: 修改成功或者失败.
        """
        date_time = datetime.datetime.strptime(modify_time_str, "%Y%m%d%H%M%S%f")
        date_command = f"date {date_time.year}-{date_time.month}-{date_time.day}"
        result_date = subprocess.run(date_command, shell=True, check=False)
        time_command = f"time {date_time.hour}:{date_time.minute}:{date_time.second}"
        result_time = subprocess.run(time_command, shell=True, check=False)
        if result_date.returncode == 0 and result_time.returncode == 0:
            return True
        return False

    @staticmethod
    def get_log_format() -> str:
        """获取日志格式字符串.

        Returns:
            str: 返回日志格式字符串.
        """
        return "%(asctime)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s"

    @staticmethod
    def create_log_dir():
        """判断log目录是否存在, 不存在就创建."""
        log_dir = pathlib.Path(f"{os.getcwd()}/log")
        if not log_dir.exists():
            os.mkdir(log_dir)

    @staticmethod
    def get_current_thread_name():
        """获取当前线程名称."""
        return threading.current_thread().name

    @staticmethod
    def try_except_exception(exception_type: Exception):
        """根据传进来的异常类型返回装饰器函数.

        Args:
            exception_type (Exception): 要抛出的异常.

        Returns:
            function: 返回装饰器函数.
        """
        def wrap(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    raise exception_type from exc
            return wrapper
        return wrap

    @staticmethod
    def get_inovance_dll_path() -> str:
        """获取汇川plc标签通讯的dll路径.

        Returns:
            str: 返回汇川plc标签通讯的dll路径.
        """
        return f"{os.getcwd()}/equipment_cyg/external/inovance_tag_dll/TagAccessCS.dll"

    def get_alarm_path(self) -> Optional[pathlib.Path]:
        """获取报警表格的路径.

        Returns:
            Optional[pathlib.Path]: 返回报警表格路径, 找不到返回None.
        """
        module_name = self.__module__.rsplit(".", maxsplit=1)[-1]
        path = pathlib.Path(f"{os.getcwd()}/equipment_cyg/product/{module_name}/cyg_alarm.csv")
        if path.exists():
            return path
        return None

    @property
    def file_handler(self) -> TimedRotatingFileHandler:
        """设置保存日志的处理器, 每个一天自动生成一个日志文件.

        Returns:
            TimedRotatingFileHandler: 返回 TimedRotatingFileHandler 日志处理器.
        """
        if self._file_handler is None:
            logging.basicConfig(level=logging.INFO, encoding="UTF-8", format=self.get_log_format())
            log_file_name = f"{os.getcwd()}/log/{datetime.datetime.now().strftime('%Y-%m-%d')}"
            self._file_handler = TimedRotatingFileHandler(
                log_file_name, when="D", interval=1, backupCount=10, encoding="UTF-8"
            )
            self._file_handler.setFormatter(logging.Formatter(self.get_log_format()))
        return self._file_handler
    