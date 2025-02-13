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
import time
from logging.handlers import TimedRotatingFileHandler
from typing import Union, Optional, Callable

from inovance_tag.exception import PLCWriteError, PLCReadError, PLCRuntimeError
from inovance_tag.tag_communication import TagCommunication
from inovance_tag.tag_type_enum import TagTypeEnum
from secsgem.common import DeviceType, Message
from secsgem.gem import CollectionEvent, GemEquipmentHandler, StatusVariable, RemoteCommand, Alarm, DataValue, \
    EquipmentConstant
from secsgem.secs.data_items.tiack import TIACK
from secsgem.secs.functions import SecsS02F18
from secsgem.secs.variables import U4, Array, Base, String
from secsgem.hsms import HsmsSettings, HsmsConnectMode

from equipment_cyg.controller.enum_sece_data_type import EnumSecsDataType


# pylint: disable=W1203
class Controller(GemEquipmentHandler):  # pylint: disable=R0901, R0904
    """Equipment controller class."""

    def __init__(self, **kwargs):
        self.config = self.get_config(self.get_config_path(f"{'/'.join(self.__module__.split('.'))}.json"))
        self.plc = None
        self._file_handler = None  # 保存日志的处理器

        hsms_settings = HsmsSettings(
            address=self.get_config_value("secs_ip", "127.0.0.1", parent_name="secs_conf"),
            port=self.get_config_value("secs_port", 5000, parent_name="secs_conf"),
            connect_mode=getattr(
                HsmsConnectMode, self.get_config_value("connect_mode", "PASSIVE", parent_name="secs_conf"),
            ),
            device_type=DeviceType.EQUIPMENT
        )
        super().__init__(settings=hsms_settings, **kwargs)

        self.model_name = self.get_config_value("model_name", parent_name="secs_conf")
        self.software_version = self.get_config_value("software_version", parent_name="secs_conf")
        self.recipes = self.get_config_value("recipes", {})  # 获取所有上传过的配方信息
        self.alarm_id = U4(0)  # 保存报警id
        self.alarm_text = ""  # 保存报警内容

        self._initial_log_config()
        self._initial_evnet()
        self._initial_status_variable()
        self._initial_data_value()
        self._initial_equipment_constant()
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

    def _initial_data_value(self):
        """加载定义好的 data value."""
        data_values = self.config.get("data_values", {})
        for data_name, data_info in data_values.items():
            data_id = data_info.get("dvid")
            value_type_str = data_info.get("value_type")
            value_type = getattr(EnumSecsDataType, value_type_str).value
            data_info["value_type"] = value_type
            self.data_values.update({data_id: DataValue(name=data_name, **data_info)})
            data_info["value_type"] = value_type_str

    def _initial_equipment_constant(self):
        """加载定义好的常量."""
        equipment_constants = self.config.get("equipment_constant", {})
        for ec_name, ec_info in equipment_constants.items():
            ec_id = ec_info.get("ecid")
            value_type_str = ec_info.get("value_type")
            value_type = getattr(EnumSecsDataType, value_type_str).value
            ec_info["value_type"] = value_type
            ec_info.update({"min_value": 0, "max_value": 0})
            self.equipment_constants.update({ec_id: EquipmentConstant(name=ec_name, **ec_info)})
            ec_info["value_type"] = value_type_str

    def _initial_remote_command(self):
        """加载定义好的远程命令."""
        remote_commands = self.config.get("remote_commands", {})
        for rc_name, rc_info in remote_commands.items():
            ce_id = rc_info.get("ce_id")
            self.remote_commands.update({rc_name: RemoteCommand(name=rc_name, ce_finished=ce_id, **rc_info)})

    def _initial_alarm(self):
        """加载定义好的报警."""
        if alarm_path := self.get_alarm_path():
            with pathlib.Path(alarm_path).open("r+") as file:  # pylint: disable=W1514
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
        """Host查看设备的所有配方."""
        del handler
        recipes = [recipe_id_name.split("_")[-1] for recipe_id_name in list(self.config["recipes"].keys())]
        return self.stream_function(7, 20)(recipes)

    def _on_s07f25(self, handler, packet):
        """host请求格式化配方信息."""
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
                    if sv_id in self.status_variables:
                        sv_instance: StatusVariable = self.status_variables.get(sv_id)
                    else:
                        sv_instance: DataValue = self.data_values.get(sv_id)
                    if issubclass(sv_instance.value_type, Array):
                        try:
                            value = Array(U4, sv_instance.value)
                        except Exception:
                            value = Array(String, sv_instance.value)
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

    def get_callback_tag(self, signal_name: str) -> list:
        """根据 signal_name 获取对应的 callback.

        Args:
            signal_name: 信号名称.

        Returns:
            list: 要执行的操作列表.
        """
        return self.get_config_value("plc_signal_tag_name")[signal_name].get("call_back")

    def get_tag_name(self, name):
        """根据传入的 name 获取 plc 定义的标签.

        Args:
            name (str): 配置文件里给 plc 标签自定义的变量名.

        Returns:
            str: 返回 plc 定义的标签
        """
        return self.config["plc_signal_tag_name"][name]["tag_name"]

    def get_siemens_start(self, name) -> int:
        """根据传入的 name 获取西门子 plc 定义的变量的起始位.

        Args:
            name (str): 配置文件里给 plc 变量自定义的起始位.

        Returns:
            int: 返回变量的起始位.
        """
        return self.config["plc_signal_start"][name]["start"]

    @staticmethod
    def get_recipe_id_name(recipe_name: str, recipes: dict) -> Optional[str]:
        """根据配方名称获取配方id和name."""
        for recipe_id_name, recipe_info in recipes.items():
            if recipe_name and str(recipe_name) in recipe_id_name:
                return recipe_id_name
        return None

    def get_modbus_start(self, name) -> int:
        """根据传入的 name 获取modbus plc 定义的变量的起始位.

        Args:
            name (str): 配置文件里给 plc 变量自定义的起始位.

        Returns:
            int: 返回变量的起始位.
        """
        return self.config["plc_signal_start"][name]["start"]

    def get_modbus_bit_index(self, name) -> int:
        """根据传入的 name 获取modbus plc 定义的变量的bit 索引.

        Args:
            name (str): 配置文件里给 plc 变量自定义的起始位.

        Returns:
            int: 返回bool的bit索引.
        """
        return self.config["plc_signal_start"][name]["bit_index"]

    def get_modbus_data_type(self, name):
        """根据传入的 name 获取 modbus plc 定义的地址的 data_type.

        Args:
            name (str): 配置文件里给 plc 标签自定义的变量名.

        Returns:
            str: 返回 plc 定义的地址的data_type
        """
        return self.config["plc_signal_tag_name"][name]["data_type"]

    def get_mitsubishi_address(self, name) -> str:
        """根据传入的 name 获取三菱 plc 定义的变量的地址.

        Args:
            name (str): 配置文件里给 plc 变量自定义的地址.

        Returns:
            str: 返回变量的地址.
        """
        return self.config["plc_signal_start"][name]["start"]

    def get_mitsubishi_address_size(self, name) -> int:
        """根据传入的 name 获取三菱 plc 定义的变量的地址大小.

        Args:
            name (str): 配置文件里给 plc 变量自定义的地址.

        Returns:
            str: 返回变量的地址大小.
        """
        return self.config["plc_signal_start"][name]["size"]

    def get_siemens_size(self, name) -> int:
        """根据传入的 name 获取西门子 plc 定义的变量的大小.

        Args:
            name (str): 配置文件里给 plc 变量自定义的变量名称.

        Returns:
            int: 返回变量的大小.
        """
        return self.config["plc_signal_start"][name]["start"]

    def get_tag_data_type(self, name):
        """根据传入的 name 获取 plc 定义的标签的 data_type.

        Args:
            name (str): 配置文件里给 plc 标签自定义的变量名.

        Returns:
            str: 返回 plc 定义的标签的data_type
        """
        return self.config["plc_signal_tag_name"][name]["data_type"]

    def get_address_data_type(self, name):
        """根据传入的 name 获取 plc 定义的地址位的 data_type.

        Args:
            name (str): 配置文件里给 plc 地址自定义的变量名.

        Returns:
            str: 返回 plc 定义的地址位的data_type
        """
        return self.config["plc_signal_start"][name]["data_type"]

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

    def get_dv_id_with_name(self, dv_name: str) -> Optional[int]:
        """根据data名获取data id.

        Args:
            dv_name: 变量名称.

        Returns:
            Optional[int]: 返回data id, 没有此data返回None.
        """
        if sv_info := self.get_config_value("data_values").get(dv_name):
            return sv_info["dvid"]
        return None

    def get_sv_value_with_name(self, sv_name: str) -> Union[int, str, bool, list, float]:
        """根据变量名获取变量值.

        Args:
            sv_name: 变量名称.

        Returns:
            Union[int, str, bool, list, float]: 返回对应变量的值.
        """
        return self.status_variables.get(self.get_sv_id_with_name(sv_name)).value

    def get_dv_value_with_name(self, dv_name: str) -> Union[int, str, bool, list, float]:
        """根据data名获取data值.

        Args:
            dv_name: data名称.

        Returns:
            Union[int, str, bool, list, float]: 返回对应变量的值.
        """
        return self.data_values.get(self.get_dv_id_with_name(dv_name)).value

    def get_ec_id_with_name(self, ec_name: str) -> Optional[int]:
        """根据常量名获取常量 id.

        Args:
            ec_name: 常量名称.

        Returns:
            Optional[int]: 返回常量 id, 没有此常量返回None.
        """
        if ec_info := self.get_config_value("equipment_constant").get(ec_name):
            return ec_info["ecid"]
        return None

    def get_sv_name_with_id(self, sv_id: int) -> Optional[str]:
        """根据变量id获取变量名称.

        Args:
            sv_id: 变量id.

        Returns:
            Optional[int]: 返回变量名称, 没有此变量返回None.
        """
        if sv_instance := self.status_variables.get(sv_id):
            return sv_instance.name
        return None

    def get_ec_value_with_name(self, ec_name: str) -> Union[int, str, bool, list, float]:
        """根据常量名获取常量值.

        Args:
            ec_name: 常量名称.

        Returns:
            Union[int, str, bool, list, float]: 返回对应常量的值.
        """
        return self.equipment_constants.get(self.get_ec_id_with_name(ec_name)).value

    def set_sv_value_with_name(self, sv_name: str, sv_value: Union[str, int, float, list]):
        """设置指定变量的值.

        Args:
            sv_name (str): 变量名称.
            sv_value (Union[str, int, float, list]): 要设定的值.
        """
        self.status_variables.get(self.get_sv_id_with_name(sv_name)).value = sv_value

    def set_dv_value_with_name(self, dv_name: str, dv_value: Union[str, int, float, list]):
        """设置指定变量的值.

        Args:
            dv_name (str): 变量名称.
            dv_value (Union[str, int, float, list]): 要设定的值.
        """
        self.data_values.get(self.get_dv_id_with_name(dv_name)).value = dv_value

    def set_ec_value_with_name(self, ec_name: str, ec_value: Union[str, int, float]):
        """设置指定变量的值.

        Args:
            ec_name (str): 变量名称.
            ec_value (Union[str, int, float]): 要设定的值.
        """
        self.equipment_constants.get(self.get_ec_id_with_name(ec_name)).value = ec_value

    def save_current_recipe_name_local(self, plc_instance: Union[TagCommunication], recipe_name: str = None):
        """保存当前的配方name.

        Args:
            plc_instance: plc实例.
            recipe_name: 要保存的配方名称.
        """
        if recipe_name is None:
            recipe_name = plc_instance.execute_read(self.get_tag_name("current_recipe_name"), "string")
        self.set_sv_value_with_name("current_recipe_name", recipe_name)
        self.config["status_variable"]["current_recipe_name"]["value"] = recipe_name
        self.update_config(f"{'/'.join(self.__module__.split('.'))}.json", self.config)

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
            # noinspection PyTypeChecker
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

    def get_alarm_path(self) -> Optional[pathlib.Path]:
        """获取报警表格的路径.

        Returns:
            Optional[pathlib.Path]: 返回报警表格路径, 找不到返回None.
        """
        module_dirs = self.__module__.split(".")
        module_path = "/".join(module_dirs[:len(module_dirs) - 1])
        path = pathlib.Path(f"{os.getcwd()}/{module_path}/cyg_alarm.csv")
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

    def start_monitor_plc_thread(self, plc_type: str):
        """启动监控 plc 信号的线程.

        Args:
            plc_type (str): plc类型.
        """
        if self.plc.communication_open():
            self.logger.warning(f"*** First connect to plc success *** -> plc地址是: {self.plc.ip}.")
        else:
            self.logger.warning(f"*** First connect to plc failure *** -> plc地址是: {self.plc.ip}.")
        getattr(self, f"mes_heart_thread_{plc_type}")()  # 心跳线程
        getattr(self, f"control_state_thread_{plc_type}")()  # 控制状态线程
        getattr(self, f"machine_state_thread_{plc_type}")()  # 运行状态线程
        getattr(self, f"bool_signal_thread_{plc_type}")()  # bool类型信号线程

    def mes_heart_thread_tag(self):
        """mes 心跳的线程."""

        def _mes_heart():
            """mes 心跳, 每隔指定间隔时间写入一次."""
            tag_name = self.get_tag_name("mes_heart")
            while True:
                try:
                    self.plc.execute_write(tag_name, TagTypeEnum.BOOL.value, True, save_log=False)
                    time.sleep(self.get_dv_value_with_name("mes_heart_time_gap"))
                    self.plc.execute_write(tag_name, TagTypeEnum.BOOL.value, False, save_log=False)
                    time.sleep(self.get_dv_value_with_name("mes_heart_time_gap"))
                except PLCWriteError as e:
                    self.logger.warning(f"*** Write failure: mes_heart *** -> reason: {str(e)}!")
                    if self.plc.communication_open() is False:
                        wait_time = self.get_dv_value_with_name("reconnect_plc_wait_time")
                        self.logger.warning(f"*** Plc connect attempt *** -> wait {wait_time}s attempt connect again.")
                        time.sleep(wait_time)
                    else:
                        self.logger.warning(f"*** After exception plc connect success *** -> plc地址是: {self.plc.ip}.")

        threading.Thread(target=_mes_heart, daemon=True, name="mes_heart_thread").start()

    def control_state_thread_tag(self):
        """控制状态变化的线程."""

        def _control_state():
            """监控控制状态变化."""
            tag_name = self.get_tag_name("control_state")
            while True:
                try:
                    control_state = self.plc.execute_read(tag_name, TagTypeEnum.INT.value, save_log=False)
                    if control_state != self.get_sv_value_with_name("current_control_state"):
                        self.set_sv_value_with_name("current_control_state", control_state)
                        self.send_s6f11("control_state_change")
                except PLCReadError as e:
                    self.logger.warning(f"*** Read failure: control_state *** -> reason: {str(e)}!")
                    time.sleep(self.get_dv_value_with_name("reconnect_plc_wait_time"))

        threading.Thread(target=_control_state, daemon=True, name="control_state_thread").start()

    def machine_state_thread_tag(self):
        """运行状态变化的线程."""

        def _machine_state():
            """监控运行状态变化."""
            tag_name = self.get_tag_name("machine_state")
            while True:
                try:
                    machine_state = self.plc.execute_read(tag_name, TagTypeEnum.INT.value, save_log=False)
                    if machine_state != self.get_sv_value_with_name("current_machine_state"):
                        alarm_state = self.get_dv_value_with_name("alarm_state")
                        if machine_state == alarm_state:
                            self.set_clear_alarm_tag(self.get_dv_value_with_name("occur_alarm_code"))
                        elif self.get_sv_value_with_name("current_machine_state") == alarm_state:
                            self.set_clear_alarm_tag(self.get_dv_value_with_name("clear_alarm_code"))
                        self.set_sv_value_with_name("current_machine_state", machine_state)
                        self.send_s6f11("machine_state_change")
                except PLCReadError as e:
                    self.logger.warning(f"*** Read failure: machine_state *** -> reason: {str(e)}!")
                    time.sleep(self.get_dv_value_with_name("reconnect_plc_wait_time"))

        threading.Thread(target=_machine_state, daemon=True, name="machine_state_thread").start()

    def set_clear_alarm_tag(self, alarm_code: int):
        """通过S5F1发送报警和解除报警.

        Args:
            alarm_code (int): 报警类型.
        """
        if alarm_code == self.get_dv_value_with_name("occur_alarm_code"):
            alarm_id_str = self.plc.execute_read(self.get_tag_name("alarm_id"), TagTypeEnum.STRING.value)
            self.logger.info(f"*** 当前报警id是: {alarm_id_str} ***")
            self.alarm_id = U4(int(alarm_id_str))
            if self.alarms.get(alarm_id_str):
                self.alarm_text = self.alarms.get(alarm_id_str).text
            else:
                self.alarm_text = "Occur Alarm, but alarm is not defined in alarm csv file."
            self.logger.info(f"*** 当前报警text是: {self.alarm_text} ***")

        def _alarm_sender(_alarm_code):
            self.send_and_waitfor_response(
                self.stream_function(5, 1)({
                    "ALCD": _alarm_code, "ALID": self.alarm_id, "ALTX": self.alarm_text
                })
            )

        threading.Thread(target=_alarm_sender, args=(alarm_code,), daemon=True).start()

    def bool_signal_thread_tag(self):
        """bool 类型信号的线程."""

        def _bool_signal(**kwargs):
            """监控 plc bool 信号."""
            self.monitor_plc_address_tag(**kwargs)  # 实时监控plc信号

        plc_signal_dict = self.get_config_value("plc_signal_tag_name", {})
        for signal_name, signal_info in plc_signal_dict.items():
            if signal_info.get("loop", False):  # 实时监控的信号才会创建线程
                threading.Thread(
                    target=_bool_signal, daemon=True, kwargs=signal_info, name=f"{signal_name}_thread"
                ).start()

    def monitor_plc_address_tag(self, **signal_info):
        """实时监控plc信号.

        Args:
            signal_info (dict): 要监控的信号信息.
        """
        signal_value, data_type = signal_info.get("value"), signal_info.get("data_type")
        while True:
            # noinspection PyBroadException
            try:
                current_value = self.plc.execute_read(signal_info.get("tag_name"), data_type, False)
                if current_value == signal_value:
                    self.signal_trigger_event(signal_info.get("call_back", []), signal_info, plc_type="tag")  # 监控到bool信号触发事件
                time.sleep(0.001)
            except Exception:  # pylint: disable=W0718
                pass  # 出现任何异常不做处理

    def signal_trigger_event(self, call_back_list: list, signal_info: dict, plc_type: str):
        """监控到信号触发事件.

        Args:
            call_back_list (list): 要执行的操作信息列表.
            signal_info (dict): 信号信息.
            plc_type (str): plc类型.
        """
        self.logger.info(f"{'=' * 40} 监控到信号: {signal_info.get('description')} {'=' * 40}")
        self.execute_call_backs(call_back_list, plc_type=plc_type)  # 根据配置文件下的call_back执行具体的操作
        self.logger.info(f"{'=' * 40} 流程结束: {signal_info.get('description')} {'=' * 40}")

    def is_send_event(self, call_back):
        """判断是否要发送事件."""
        if (event_name := call_back.get("event_name")) in self.get_config_value("collection_events"):  # 触发事件
            if event_name == "track_out_carrier":
                time.sleep(5)
            self.send_s6f11(event_name)

    @try_except_exception(PLCRuntimeError("*** Execute call backs error ***"))
    def execute_call_backs(self, call_backs: list, plc_type: str):
        """根据操作列表执行具体的操作.

        Args:
            call_backs (list): 要执行动作的信息列表, 按照列表顺序执行.
            plc_type (str): plc类型.

        Raises:
            PLCRuntimeError: 在执行配置文件下的步骤时出现异常.
        """
        for i, call_back in enumerate(call_backs, 1):
            self.logger.info(f"{'-' * 30} Step {i} 开始: {call_back.get('description')} {'-' * 30}")
            operation_func = self.get_operation_func(call_back.get("operation_type"))
            operation_func(call_back=call_back, plc_type=plc_type)
            self.is_send_event(call_back)
            self.logger.info(f"{'-' * 30} 结束 Success: {call_back.get('description')} {'-' * 30}")

    def read_operation_update_sv_or_dv(self, call_back: dict, plc_type: str):
        """读取 plc 数据, 更新sv.

        Args:
            call_back (dict): 读取地址位的信息.
            plc_type (str): plc类型.
        """
        getattr(self, f"read_operation_update_sv_or_dv_{plc_type}")(call_back)

    def read_operation_update_sv_or_dv_tag(self, call_back: dict):
        """读取 plc 数据, 更新sv.

        Args:
            call_back (dict): 读取地址位的信息.
        """
        tag_name, data_type = call_back.get("tag_name"), call_back.get("data_type")
        # 先判断有木有前提条件
        if premise_tag_name := call_back.get("premise_tag_name"):
            plc_value = self.read_with_condition_tag(
                tag_name, premise_tag_name,
                data_type, call_back.get("premise_data_type"),
                call_back.get("premise_value"), time_out=call_back.get("premise_time_out", 5)
            )
        else:
            # 直接读取
            plc_value = self.plc.execute_read(tag_name, data_type)
            self.logger.info(f"*** 读取到plc值: {plc_value} ***")

        self.update_sv_or_dv_value(plc_value, call_back)

    def update_sv_or_dv_value(self, plc_value: Union[int, bool, str, float], call_back: dict):
        """更新sv或dv的值.

        Args:
            plc_value (Union[int, bool, str, float]): 读取到的plc值.
            call_back (dict): 要更新的sv或dv的信息.
        """
        if dv_name := call_back.get("dv_name"):
            self.logger.info(f"*** 更新dv值: {dv_name} *** 值为: {plc_value} ***")
            self.set_dv_value_with_name(dv_name, plc_value)
        elif sv_name := call_back["value"].get("sv_name"):
            self.logger.info(f"*** 更新sv值: {sv_name} *** 值为: {plc_value} ***")
            self.set_sv_value_with_name(sv_name, plc_value)

    def read_with_condition_tag(
            self, tag_name: str, premise_tag_name: str, data_type: str,
            premise_data_type: str, premise_value: Union[int, bool, str, float], time_out: int
    ) -> Union[str, int, bool, float, list]:
        """根据条件信号读取指定地址位的值.

        Args:
            tag_name (str): 要读取地址位的起始位.
            premise_tag_name (str): 前提条件地址位的起始位.
            data_type (str): 要读取数据类型.
            premise_data_type (str): 前提条件数据类型.
            premise_value (Union[int, bool, str, float]): 前提条件的值.
            time_out (int): 超时时间.

        Returns:
            Union[str, int, bool, float, list]: 返回去读地址的值.
        """
        self.read_condition_value_tag(premise_tag_name, premise_data_type, premise_value, time_out)
        return self.plc.execute_read(tag_name, data_type)

    def read_condition_value_tag(
            self, premise_tag_name: str, premise_data_type: str, premise_value: Union[int, bool], time_out: int):
        """读取条件值.

        Args:
            premise_tag_name: 前提条件信号的地址位置.
            premise_data_type: 前提条件数据类型.
            premise_value: 前提条件的值.
            time_out: 超时时间.
        """
        count = 1
        while (real_premise_value := self.plc.execute_read(premise_tag_name, premise_data_type)) != premise_value:
            self.logger.info(f"*** 第 %s 次读取前提值 *** 实际值: %s, 期待值: %s", count, real_premise_value, premise_value)
            count += 1
            time_out -= 1
            time.sleep(1)
            if time_out == 0:
                self.logger.error(f"*** plc 未回复 *** -> plc 未在 {time_out}s 内回复")
                break

    def write_operation(self, call_back: dict, plc_type: str):
        """向 plc 地址位写入数据.

        Args:
            call_back (dict): 要写入值的地址位信息.
            plc_type (str): plc类型.
        """
        getattr(self, f"write_operation_{plc_type}")(call_back)

    def write_operation_tag(self, call_back: dict):
        """向 plc 地址位写入数据.

        Args:
            call_back (dict): 要写入值的地址位信息.
        """
        tag_name, data_type = call_back.get("tag_name"), call_back.get("data_type")
        write_value = self.get_real_write_value(call_back.get("value"))

        # 先判断有木有前提条件
        if premise_tag_name := call_back.get("premise_tag_name"):
            self.write_with_condition_tag(
                tag_name, premise_tag_name, call_back.get("data_type"), call_back.get("premise_data_type"),
                call_back.get("premise_value"), write_value, call_back.get("premise_time_out", 5)
            )
            return

        if isinstance(write_value, list):
            # 是列表写入多个值
            for i, value in enumerate(write_value, 1):
                self.plc.execute_write(f"{tag_name}[{i}]", data_type, value)
        else:
            # 不是列表写入单个值
            self.plc.execute_write(tag_name, data_type, write_value)

    def write_with_condition_tag(
            self, tag_name: str, premise_tag_name: str, data_type: str, premise_data_type: str,
            premise_value: Union[bool, int, float, str], write_value: Union[bool, int, float, str], time_out: int):
        """Write value with condition.

        Args:
            tag_name: 要清空信号的地址位置.
            premise_tag_name: 前提条件信号的地址位置.
            data_type: 要写入数据类型.
            premise_data_type: 前提条件数据类型.
            premise_value: 清空地址的判断值.
            write_value: 要写入的数据.
            time_out: 超时时间.
        """
        self.read_condition_value_tag(premise_tag_name, premise_data_type, premise_value, time_out)
        self.plc.execute_write(tag_name, data_type, write_value)

    def get_real_write_value(self, value_flag: Union[int, float, bool, str]) -> Union[int, float, bool, str]:
        """获取写入值.

        Args:
            value_flag: 写入值标识符.

        Returns:
            Optional[Union[int, float, bool, str]]: 写入值.
        """
        if "sv" in str(value_flag):
            return self.get_sv_value_with_name(value_flag.split(":")[-1])
        if "dv" in str(value_flag):
            return self.get_dv_value_with_name(value_flag.split(":")[-1])
        return value_flag

    def get_operation_func(self, operation_type: str) -> Callable:
        """获取操作函数.

        Args:
            operation_type (str): 操作类型.

        Returns:
            Callable: 操作函数.
        """
        operation_func_map = {
            "read": self.read_operation_update_sv_or_dv,
            "write": self.write_operation,
            "wait_eap_reply": self.wait_eap_reply,
            "save_recipe": self.save_recipe
        }
        return operation_func_map[operation_type]

    def wait_eap_reply(self, *args, **kwargs):
        """等待EAP回复进站."""
        self.logger.info(args, kwargs)
        while not self.get_dv_value_with_name("reply_flag"):
            self.logger.info("EAP 未回复, 等待 0.2 秒")
            time.sleep(0.2)
        self.set_dv_value_with_name("reply_flag", False)

    def save_recipe(self, *args, **kwargs):
        """保存上传的recipe."""
        self.logger.info(args, kwargs)
        upload_recipe_id = self.get_dv_value_with_name("upload_recipe_id")
        upload_recipe_name = self.get_dv_value_with_name("upload_recipe_name")
        upload_recipe_id_name = f"{upload_recipe_id}_{upload_recipe_name}"
        self.config["recipes"].update({upload_recipe_id_name: {}})
        self.update_config(f"{'/'.join(self.__module__.split('.'))}.json", self.config)

    def on_sv_value_request(self, sv_id: Base, status_variable: StatusVariable) -> Base:
        """Get the status variable value depending on its configuration.

        Args:
            sv_id (Base): The id of the status variable encoded in the corresponding type.
            status_variable (StatusVariable): The status variable requested.

        Returns:
            The value encoded in the corresponding type
        """
        self.save_current_recipe_name_local(self.plc)
        del sv_id
        # noinspection PyTypeChecker
        if issubclass(status_variable.value_type, Array):
            return status_variable.value_type(U4, status_variable.value)
        return status_variable.value_type(status_variable.value)

    def get_dv_base_value_type_with_name(self, dv_name: str) -> callable:
        """根据data名获取列表数据元素的类型.

        Args:
            dv_name: data名称.

        Returns:
           str: 列表数据元素的类型.
        """
        data_value_instance = self.data_values.get(self.get_dv_id_with_name(dv_name))
        if hasattr(data_value_instance, "base_value_type"):
            func_str = data_value_instance.base_value_type
            if func_str == "UINT_4":
                return int
            if func_str == "F4":
                return float
            if func_str == "BOOL":
                return bool
            if func_str == "ASCII":
                return str
        return None