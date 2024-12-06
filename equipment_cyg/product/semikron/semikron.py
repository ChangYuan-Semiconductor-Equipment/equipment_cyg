# pylint: skip-file
"""
监控托盘进站信号:  92.1 bool
    1.读取托盘码  190.0 string[80]
    2.写入托盘进站反馈信息
        1.写入配方id  274 int
        2.写入进站结果  272.0 int 1: 可做, 2: 不可做, 3: 首件, 4:尾料
    3.通知plc拿进站结果  166.1 bool
    4.监控托盘进站信号为 False 清空通知信号  92.1 bool - 166.1 bool

工位1托盘请求信号:  92.2 bool
    1.读取工位1托盘码  2812.0 string[80]
    2.写入工位1托盘请求反馈信息
        1.写入配方id  2896 int
        2.写入进站结果  2894.0 int 1: 可做, 2: 不可做, 3: 首件, 4:尾料
        3.写入工位1托盘里的DBC信息
            1.写入DBC码  2898 string[80]
            2.写入DBC状态  2980 int  1: OK, 2: NG, 3: Empty
    3.通知plc拿工位1托盘信息  166.2 bool
    4.监控工位1托盘请求信号为 False 清空通知信号  92.2 bool - 166.2 bool

工位2托盘请求信号:  92.3 bool
    1.读取工位2托盘码  5518.0 string[80]
    2.写入工位2托盘请求反馈信息
        1.写入配方id  5602 int
        2.写入进站结果  5600.0 int 1: 可做, 2: 不可做, 3: 首件, 4:尾料
        3.写入工位1托盘里的DBC信息
            1.写入DBC码  5604 string[80]
            2.写入DBC状态  5686 int  1: OK, 2: NG, 3: Empty
    3.通知plc拿工位2托盘信息  166.3 bool
    4.监控工位1托盘请求信号为 False 清空通知信号  92.3 bool - 166.3 bool

左侧入料 Tray 盘:  94.1 bool
    1.读取DBC信息
        1.读取DBC状态  8542 int
        2.读取DBC码  8632 string[80]
        3.读取tray码  8550 string[80]
        4.读取DBC在tray盘的穴位号  8544 int
    2.MES 回复左侧入料 Tray 盘信号  168.1 bool
    3.监控左侧入料 Tray 盘信号为 False 清空MES 回复信号  94.1 bool - 168.1 bool

右侧侧入料 Tray 盘:  94.2 bool
    1.读取DBC信息
        1.读取DBC状态  8976 int
        2.读取DBC码  9066 string[80]
        3.读取tray码  8984 string[80]
        4.读取DBC在tray盘的穴位号  8978 int
    2.MES 回复左侧入料 Tray 盘信号  168.2 bool
    3.监控左侧入料 Tray 盘信号为 False 清空MES 回复信号  94.2 bool - 168.2 bool

NG DBC入料 Tray 盘:  94.3 bool
    1.读取NG DBC信息
        1.读取NG DBC状态  9410 int
        2.读取NG DBC码  9500 string[80]
    2.MES 回复NG DBC入料 Tray 盘信号  168.3 bool
    3.监控NG DBC入料 Tray 盘信号为 False 清空MES 回复信号  94.3 bool - 168.3 bool
"""
import asyncio
import json
import os.path
import threading
import time
from typing import Union, Optional

import pandas as pd
from future.backports.datetime import datetime
from inovance_tag.exception import PLCReadError, PLCRuntimeError, PLCWriteError
from mysql_api.exception import MySQLAPIAddError
from mysql_api.mysql_database import MySQLDatabase
from mysql_table_model.semikron import LotInfo, DbcLinkTray, Point, Recipe
from secsgem.secs.variables import U4
from siemens_plc.s7_plc import S7PLC
from socket_cyg.socket_server_asyncio import CygSocketServerAsyncio

from equipment_cyg.controller.controller import Controller


# noinspection DuplicatedCode,PyBroadException
class Semikron(Controller):  # pylint: disable=R0901
    """Semikron转盘设备 class."""

    def __init__(self):
        super().__init__()

        self.mysql = MySQLDatabase(
            self.get_ec_value_with_name("mysql_user_name"),
            self.get_ec_value_with_name("mysql_password")
        )
        self.set_current_recipe_id()
        self.db_num = self.get_ec_value_with_name("plc_db_num")
        self.current_alarm_id = self.get_dv_value_with_name("current_alarm_id")
        self.current_alarm_text = self.get_dv_value_with_name("current_alarm_text")
        self.plc = S7PLC(
            self.get_ec_value_with_name("plc_ip"),
            self.get_ec_value_with_name("plc_rack"),
            self.get_ec_value_with_name("plc_slot")
        )
        self.plc.logger.addHandler(self.file_handler)  # 保存plc日志到文件

        self.socket_server = CygSocketServerAsyncio(
            self.get_ec_value_with_name("socket_server_ip"),
            self.get_ec_value_with_name("socket_server_port")
        )
        self.socket_server.logger.addHandler(self.file_handler)  # 保存socket日志到文件
        self.start_socket_server_thread()  # 启动接收web请求的socket服务

        self.enable_equipment()  # 启动MES服务

        self.start_monitor_plc_thread()  # 启动监控plc信号线程

    def set_current_recipe_id(self):
        """设置当前配方的id."""
        current_recipe_name = self.get_sv_value_with_name("current_recipe_name")
        recipe_id = self.get_recipe_id_with_name(current_recipe_name)
        self.set_dv_value_with_name("current_recipe_id", recipe_id)

    # 启动接收web请求的socket服务
    def start_socket_server_thread(self):
        """启动监控 web 页面发来的请求."""
        self.socket_server.operations_return_data = self.operations_return_data

        def _run_socket_server():
            asyncio.run(self.socket_server.run_socket_server())

        thread = threading.Thread(target=_run_socket_server, daemon=True)  # 主程序结束这个线程也结束
        thread.start()

    def start_monitor_plc_thread(self):
        """启动监控 plc 信号的线程."""
        if self.plc.communication_open():
            self.logger.warning(f"*** First connect to plc success *** -> plc地址是: {self.plc.ip}.")
        else:
            self.logger.warning(f"*** First connect to plc failure *** -> plc地址是: {self.plc.ip}.")

        self.mes_heart_thread()  # 心跳线程
        self.control_state_thread()  # 控制状态线程
        # self.machine_state_thread()  # 运行状态线程
        self.bool_signal_thread()  # bool类型信号线程

    def mes_heart_thread(self):
        """mes 心跳的线程."""

        def _mes_heart():
            """mes 心跳, 每隔 3s 写入一次."""
            start = self.get_siemens_start("mes_heart")
            while True:
                try:
                    self.plc.execute_write("bool", self.db_num, start, True)
                    time.sleep(self.get_ec_value_with_name("mes_heart_interval_time"))
                    self.plc.execute_write("bool", self.db_num, start, False)
                    time.sleep(self.get_ec_value_with_name("mes_heart_interval_time"))
                except PLCWriteError as e:
                    self.set_sv_value_with_name("current_control_state", 0)
                    self.logger.warning(f"*** Write failure: mes_heart *** -> reason: {str(e)}!")
                    if self.plc.communication_open() is False:
                        wait_time = self.get_ec_id_with_name("reconnect_plc_wait_time")
                        self.logger.warning(f"*** Plc connect attempt *** -> wait {wait_time}s attempt connect again.")
                        time.sleep(wait_time)
                    else:
                        self.logger.warning(f"*** After exception plc connect success *** -> plc地址是: {self.plc.ip}.")

        threading.Thread(target=_mes_heart, daemon=True, name="mes_heart_thread").start()

    def control_state_thread(self):
        """控制状态变化的线程."""

        def _control_state():
            """监控控制状态变化."""
            start = self.get_siemens_start("control_state")
            data_type = self.get_address_data_type("control_state")
            while True:
                try:
                    current_control_state = self.plc.execute_read(
                        data_type, self.db_num, start, 1, 1, save_log=False
                    )
                    control_state = 1 if current_control_state else 2
                    if control_state != self.get_sv_value_with_name("current_control_state"):
                        self.set_sv_value_with_name("current_control_state", control_state)
                        self.send_s6f11("control_state_change")
                except PLCReadError as e:
                    self.logger.warning(f"*** Read failure: control_state *** -> reason: {str(e)}!")
                    time.sleep(self.get_ec_value_with_name("reconnect_plc_wait_time"))

        threading.Thread(target=_control_state, daemon=True, name="control_state_thread").start()

    def machine_state_thread(self):
        """运行状态变化的线程."""

        def _machine_state():
            """监控运行状态变化."""
            start = self.get_siemens_start("machine_state")
            data_type = self.get_address_data_type("machine_state")
            while True:
                try:
                    machine_state = self.plc.execute_read(data_type, self.db_num, start, 2, save_log=False)
                    if machine_state != self.get_sv_value_with_name("current_machine_state"):
                        alarm_state = self.get_ec_value_with_name("alarm_state")
                        if machine_state == alarm_state:
                            self.set_clear_alarm(2)
                        elif self.get_sv_value_with_name("current_machine_state") == alarm_state:
                            self.set_clear_alarm(self.get_config_value("reset_alarm_code"))
                        self.set_sv_value_with_name("current_machine_state", machine_state)
                        self.send_s6f11("machine_state_change")
                except PLCReadError as e:
                    self.logger.warning(f"*** Read failure: machine_state *** -> reason: {str(e)}!")
                    time.sleep(self.get_ec_value_with_name("reconnect_plc_wait_time"))

        threading.Thread(target=_machine_state, daemon=True, name="machine_state_thread").start()

    @Controller.try_except_exception(PLCRuntimeError("*** Execute call backs error ***"))
    def execute_call_backs(self, call_backs: list):
        """根据操作列表执行具体的操作.

        Args:
            call_backs (list): 要执行动作的信息列表, 按照列表顺序执行.

        Raises:
            PLCRuntimeError: 在执行配置文件下的步骤时出现异常.
        """
        # noinspection PyTypeChecker
        operation_func_map = {
            "read": self.read_operation_update_sv_or_dv,
            "write": self.write_operation,
            "wait_eap_reply": self.wait_eap_reply
        }
        for i, call_back in enumerate(call_backs, 1):
            self.logger.info(f"{'-' * 30} Step {i} 开始: {call_back.get('description')} {'-' * 30}")
            operation_func = operation_func_map.get(call_back.get("operation_type"))
            # noinspection PyArgumentList
            operation_func(call_back=call_back)
            self.is_send_event(call_back)
            self.is_save_data_to_database(call_back)
            self.logger.info(f"{'-' * 30} 结束 Success: {call_back.get('description')} {'-' * 30}")

    # 监控 web 页面发来请求进行处理, 然后返回信息
    def operations_return_data(self, byte_data: bytes) -> Optional[str]:
        """监控 web 页面发来请求进行处理, 然后返回信息."""
        request_data = byte_data.decode("UTF-8")
        request_data_dict = json.loads(request_data)
        request_key = list(request_data_dict.keys())[0]
        request_value_dict = list(request_data_dict.values())[0]
        if request_key == "current_lot":
            return json.dumps(self.get_current_lot_info())
        if request_key == "new_lot":
            return json.dumps(self.new_lot(request_value_dict))
        if request_key == "end_lot":
            return json.dumps(self.end_lot(request_value_dict))

        return None

    def get_current_lot_info(self) -> dict:
        """获取当前工单信息, 包含工单名 所有的配方名列表 当前配方名."""

        current_lot_info = {
            "current_lot_name": self.get_sv_value_with_name("current_lot_name"),
            "current_lot_article_name": self.get_sv_value_with_name("current_lot_article_name"),
            "current_lot_quality": self.get_sv_value_with_name("current_lot_quality"),
            "current_lot_state": "正常运行" if self.get_sv_value_with_name("current_lot_state") else "工单已结束",
            "current_recipe_name": self.get_sv_value_with_name("current_recipe_name"),
            "current_point_name": self.get_sv_value_with_name("current_point_name"),
            "equipment_state": self.get_equipment_state()
        }
        return current_lot_info

    def new_lot(self, request_data_dict: dict):
        """web 页面创建工单触发的操作."""
        # 先判断上个工单是否结束
        if self.get_sv_value_with_name("current_lot_state"):
            self.set_dv_value_with_name("pp_select_state", 0)
            message = "开工单失败! 请先在当前工单页面点击 结工单 按钮以结束当前工单"
            return self.get_new_lot_response(message)
        # 先保存新工单信息
        new_lot_name = request_data_dict.get("lot_name")
        self.set_dv_value_with_name("new_lot_name", new_lot_name)
        new_lot_article_name = request_data_dict.get("lot_article_name")
        self.set_dv_value_with_name("new_lot_article_name", new_lot_article_name)
        new_lot_quality = int(request_data_dict.get("lot_quality"))
        self.set_dv_value_with_name("new_lot_quality", new_lot_quality)
        self.set_dv_value_with_name("new_lot_state", 1)

        # 设置要切换的配方id和配方名称
        point_instance = self.mysql.query_data_one(Point, point_name=new_lot_article_name[:9])
        # noinspection PyUnresolvedReferences
        recipe_name = point_instance.recipe_name
        recipe_id = self.get_recipe_id_with_name(recipe_name)
        self.set_dv_value_with_name("pp_select_recipe_id", recipe_id)
        self.set_dv_value_with_name("pp_select_recipe_name", recipe_name)

        # 设置要切换的点位名称
        point_name = request_data_dict.get("point_name")
        self.set_dv_value_with_name("pp_select_point_name", point_name)

        # 判断当前是否需要切换配方
        if recipe_name != self.get_sv_value_with_name("current_recipe_name"):
            self.execute_call_backs(self.get_callback("pp_select"))  # 切换配方
            pp_recipe_id = self.get_recipe_id_with_name(recipe_name)
            if self.get_dv_value_with_name("current_recipe_id_plc") == pp_recipe_id:
                self.execute_call_backs(self.get_callback("new_lot"))  # 写入新工单
                self.set_info_when_lot_success()
                message = "开工单成功! 并且成功切换配方"
            else:
                # 将要切换的配方id回退为current_recipe_id_plc
                self.execute_call_backs(self.get_callback("roll_back_pp_select_recipe_id"))

                self.set_dv_value_with_name("pp_select_state", 3)
                message = "开工单失败! 因为当前 plc 不允许切换配方"
        else:
            self.execute_call_backs(self.get_callback("new_lot"))  # 写入新工单
            self.set_info_when_lot_success()
            message = "开工单成功! 不需要切换配方"
        return self.get_new_lot_response(message)

    def get_new_lot_response(self, message: str) -> dict:
        response = {  # 回复web页面请求信息
            "code": 200 if self.get_dv_value_with_name("pp_select_state") == 1 else 0,
            "icon_code": 6 if self.get_dv_value_with_name("pp_select_state") == 1 else 5,
            "message": message,
            "current_lot_name": self.get_sv_value_with_name("current_lot_name"),
            "current_lot_article_name": self.get_sv_value_with_name("current_lot_article_name"),
            "current_lot_quality": self.get_sv_value_with_name("current_lot_quality"),
            "current_lot_state": "正常运行" if self.get_sv_value_with_name("current_lot_state") else "工单已结束",
            "current_recipe_name": self.get_sv_value_with_name("current_recipe_name"),
            "equipment_state": self.get_equipment_state()
        }
        return response

    def set_info_when_lot_success(self):
        """当开工单成功设置当前工单信息."""
        self.set_sv_value_with_name("current_lot_name", self.get_dv_value_with_name("new_lot_name"))
        self.set_sv_value_with_name("current_lot_article_name", self.get_dv_value_with_name("new_lot_article_name"))
        self.set_sv_value_with_name("current_lot_quality", self.get_dv_value_with_name("new_lot_quality"))
        self.set_sv_value_with_name("current_recipe_name", self.get_dv_value_with_name("pp_select_recipe_name"))
        self.set_sv_value_with_name("current_lot_state", 1)
        self.set_sv_value_with_name("current_point_name", self.get_dv_value_with_name("pp_select_point_name"))

        self.set_dv_value_with_name("current_recipe_id", self.get_dv_value_with_name("pp_select_recipe_id"))
        self.set_dv_value_with_name("pp_select_state", 1)
        self.save_current_lot_local()

    def end_lot(self, request_data_dict: dict):
        """结束工单触发的操作."""
        self.set_sv_value_with_name("current_lot_state", 0)
        self.execute_call_backs(self.get_callback("end_lot"))
        lot_name = request_data_dict.get("lot_name")

        self.mysql.update_data(LotInfo, "lot_name", lot_name, {"lot_state": 0})
        self.save_current_lot_local()
        lot_info = self.get_current_lot_info()
        lot_info.update({"icon_code": 6, "message": "成功结束工单"})
        self.save_dbc_link_to_excle(lot_name)
        return lot_info

    def save_dbc_link_to_excle(self, lot_name: str):
        """工单结束保存素具到表格."""
        results = self.mysql.query_data_all(DbcLinkTray, lot_name=lot_name)
        data_dict = [LotInfo.as_dict(result) for result in results]
        df = pd.DataFrame(data_dict)
        time_str = datetime.now().strftime("%Y-%m-%d")
        records_dir = "d:/records"
        if not os.path.exists(records_dir):
            os.mkdir(records_dir)
        df.to_excel(f"{records_dir}/{time_str}_{lot_name}.xlsx", index=False)

    def bool_signal_thread(self):
        """bool 类型信号的线程."""

        def _bool_signal(**kwargs):
            """监控 plc bool 信号."""
            self.monitor_plc_address(**kwargs)  # 实时监控plc信号

        plc_signal_dict = self.get_config_value("plc_signal_start", {})
        for signal_name, signal_info in plc_signal_dict.items():
            if signal_info.get("loop", False):  # 实时监控的信号才会创建线程
                threading.Thread(
                    target=_bool_signal, daemon=True, kwargs=signal_info, name=f"{signal_name}_thread"
                ).start()

    def monitor_plc_address(self, wait_time=0, **kwargs):
        """实时监控plc信号.

        Args:
            wait_time (int): 监控信号的时间间隔, 默认实时监控.
        """
        while True:
            # noinspection PyBroadException
            try:
                current_value = self.plc.execute_read(
                    kwargs.get("data_type", "bool"), self.db_num, kwargs.get("start"),
                    kwargs.get("size", 1), kwargs.get("bit_index"), save_log=False
                )
                current_value and self.signal_trigger_event(kwargs.get("call_back"), kwargs)  # 监控到bool信号触发事件
                time.sleep(wait_time)
            except Exception:  # pylint: disable=W0718
                pass  # 出现任何异常不做处理

    def signal_trigger_event(self, call_back_list: list, signal_info: dict):
        """监控到信号触发事件.

        Args:
            call_back_list (list): 要执行的操作信息列表.
            signal_info (dict): 信号信息.
        """
        self.logger.info(f"{'=' * 40} Get Signal: {signal_info.get('description')}, "
                         f"地址位: {signal_info.get('start')}-{signal_info.get('bit_index')} {'=' * 40}")

        self.execute_call_backs(call_back_list)  # 根据配置文件下的call_back执行具体的操作

        self.logger.info(f"{'=' * 40} Signal clear: {signal_info.get('description')} {'=' * 40}")

    def is_save_data_to_database(self, call_back):
        """保存dbc盒塑料盒的link关系到数据库."""
        if call_back.get("save_data_to_database"):
            current_thread_name = self.get_current_thread_name()
            if "left" in current_thread_name:
                dbc_link_tray_info = {
                    "dbc_code": self.get_dv_value_with_name(f"dbc_link_tray_dbc_code_left"),
                    "dbc_state": self.get_dv_value_with_name(f"dbc_link_tray_dbc_state_left"),
                    "tray_code": self.get_dv_value_with_name(f"dbc_link_tray_tray_code_left"),
                    "tray_index": self.get_dv_value_with_name(f"dbc_link_tray_tray_index_left"),
                    "lot_name": self.get_sv_value_with_name("current_lot_name"),
                    "lot_article_name": self.get_sv_value_with_name("current_lot_article_name")
                }
            elif "right" in current_thread_name:
                dbc_link_tray_info = {
                    "dbc_code": self.get_dv_value_with_name(f"dbc_link_tray_dbc_code_right"),
                    "dbc_state": self.get_dv_value_with_name(f"dbc_link_tray_dbc_state_right"),
                    "tray_code": self.get_dv_value_with_name(f"dbc_link_tray_tray_code_right"),
                    "tray_index": self.get_dv_value_with_name(f"dbc_link_tray_tray_index_right"),
                    "lot_name": self.get_sv_value_with_name("current_lot_name"),
                    "lot_article_name": self.get_sv_value_with_name("current_lot_article_name")
                }
            else:
                dbc_link_tray_info = {
                    "dbc_code": self.get_dv_value_with_name(f"dbc_link_tray_dbc_code_ng"),
                    "dbc_state": self.get_dv_value_with_name(f"dbc_link_tray_dbc_state_ng"),
                    "lot_name": self.get_sv_value_with_name("current_lot_name"),
                    "lot_article_name": self.get_sv_value_with_name("current_lot_article_name")
                }
            try:
                self.mysql.add_data(DbcLinkTray, dbc_link_tray_info)
            except MySQLAPIAddError as e:
                self.logger.error(f"*** Save dbc link tray to database failure *** -> reason: {str(e)}")

    def is_send_event(self, call_back):
        """判断是否要发送事件."""
        if (event_name := call_back.get("event_name")) in self.get_config_value("collection_events"):  # 触发事件
            self.send_s6f11(event_name)

    def write_operation(self, call_back: dict):
        """向 plc 地址位写入数据.

        Args:
            call_back (dict): 要写入值的地址位信息.
        """
        start, data_type, size = call_back.get("start"), call_back.get("data_type"), call_back.get("size")
        bit_index, write_value = call_back.get("bit_index", 0), call_back.get("value", "")

        if premise_start := call_back.get("premise_start"):
            self.write_with_condition(
                start, premise_start, call_back.get("data_type"), call_back.get("premise_data_type"),
                call_back.get("premise_size", 1), call_back.get("bit_index"), call_back.get("premise_bit_index"),
                call_back.get("premise_value"), write_value, call_back.get("premise_time_out", 5)
            )
            return
        if isinstance(write_value, list):
            self.write_value_continue(data_type, start, size, write_value, call_back.get("interval", 0))
            return
        try:
            sv_or_dv_flag, sv_or_dv_name = write_value.split(":")
            value = getattr(self, f"get_{sv_or_dv_flag}_value_with_name")(sv_or_dv_name)
        except AttributeError:
            value = write_value
        if isinstance(value, list):
            self.write_value_continue(data_type, start, size, value, call_back.get("interval", 0))
        else:
            self.plc.execute_write(data_type, self.db_num, start, value, bit_index)

    def write_value_continue(self, data_type: str, start: int, size: int, values: list, interval: int = 0):
        """连续写入数据.

        Args:
            data_type: 数据类型.
            start: 起始地址位.
            size: 单个数据的大小.
            values: 要连续写入的值.
            interval: 间隔大小.
        """
        for i, value in enumerate(values, 0):
            try:
                sv_or_dv_flag, sv_or_dv_name = value.split(":")
                value = getattr(self, f"get_{sv_or_dv_flag}_value_with_name")(sv_or_dv_name)
            except Exception:
                pass
            self.plc.execute_write(data_type, self.db_num, start + i * size + interval * i, value)

    def write_with_condition(
            self, start: int, premise_start: int,
            data_type: str, premise_data_type: str,
            premise_size: int,
            bit_index: int, premise_bit_index: int,
            premise_value: Union[bool, int, float, str], write_value: Union[bool, int, float, str],
            time_out: int,
    ):
        """Write value with condition.

        Args:
            start (int): 要清空信号的地址位置.
            premise_start (int): 前提条件信号的地址位置.
            data_type (str): 要写入数据类型.
            premise_data_type (str): 前提条件数据类型.
            premise_size(int): 前提条件标签的大小, 默认是.
            bit_index (int): 要写入数据的位索引.
            premise_bit_index (int): 前提条件标签的位索引.
            premise_value (bool): 清空地址的判断值.
            write_value (str, int): 要写入的数据.
            time_out (int): 超时时间.
        """
        count, expect_time = 1, time_out
        self.logger.info(
            f"*** Start get premise condition value *** -> 第 {count} 次读前提条件值, "
            f"start: {premise_start}, size: {premise_size}, bit_index: {premise_bit_index}"
        )
        real_premise_value = self.plc.execute_read(
            premise_data_type, self.db_num, premise_start, premise_size, premise_bit_index
        )
        self.logger.info(f"*** End get premise condition value *** -> real_value: {real_premise_value}, "
                         f"expect_value: {premise_value}")
        if premise_value == real_premise_value:
            self.plc.execute_write(data_type, self.db_num, start, write_value, bit_index)
        else:
            while time_out:
                time.sleep(1)
                count += 1
                self.logger.info(
                    f"*** Start get premise condition value *** -> 第 {count} 次读前提条件值, "
                    f"start: {premise_start}, size: {premise_size}, bit_index: {premise_bit_index}"
                )
                real_premise_value = self.plc.execute_read(
                    premise_data_type, self.db_num, premise_start, premise_size, premise_bit_index
                )
                self.logger.info(
                    f"*** End get premise condition value *** -> real_value: {real_premise_value}, "
                    f"expect_value: {premise_value}"
                )
                if premise_value == real_premise_value:
                    break
                time_out -= 1
                if time_out == 0:
                    self.logger.error(f"*** plc 超时 *** -> plc 未在 {expect_time}s 内及时回复! clear mes signal")
            self.plc.execute_write(data_type, self.db_num, start, write_value, bit_index)

    def read_operation_update_sv_or_dv(self, call_back: dict):
        """读取 plc 数据, 更新sv.

        Args:
            call_back (dict): 读取地址位的信息.
        """
        start, data_type, size = call_back.get("start"), call_back.get("data_type"), call_back.get("size")
        if premise_start := call_back.get("premise_start"):
            plc_value = self.read_with_condition(
                start, premise_start,
                data_type, call_back.get("premise_data_type"),
                size, call_back.get("premise_size", 1),
                call_back.get("bit_index"), call_back.get("premise_bit_index", 0),
                call_back.get("premise_value"), time_out=call_back.get("premise_time_out", 5)
            )
        else:
            plc_value = self.plc.execute_read(data_type, self.db_num, start, size)

        if dv_name := call_back.get("dv_name"):
            self.set_dv_value_with_name(dv_name, plc_value)
        elif sv_name := call_back.get("sv_name"):
            self.set_sv_value_with_name(sv_name, plc_value)

    def read_with_condition(
            self, start: int, premise_start: int,
            data_type: str, premise_data_type: str,
            size: int, premise_size: int,
            bit_index: int, premise_bit_index: int,
            premise_value: Union[int, bool, str, float],
            time_out=180
    ) -> Union[str, int, bool, float, list]:
        """根据条件信号读取指定地址位的值.

        Args:
            start (int): 要读取地址位的起始位.
            premise_start (int): 前提条件地址位的起始位.
            data_type (str): 要读取数据类型.
            premise_data_type (str): 前提条件数据类型.
            size (int): 要读取地址位的大小.
            bit_index (int): 要读取地址位的位索引.
            premise_bit_index (int): 前提条件地址位的位索引.
            premise_size (int): 前提条件地址位的大小.
            premise_value (Union[int, bool, str, float]): 前提条件的值.
            time_out (int): 超时时间.

        Returns:
            Union[str, int, bool, float, list]: 返回读取标签的值.
        """
        count, expect_time = 1, time_out
        self.logger.info(
            f"*** Start get premise condition value *** -> 第 {count} 次读前提条件值, "
            f"start: {premise_start}, size: {premise_size}, bit_index: {premise_bit_index}"
        )
        real_premise_value = self.plc.execute_read(
            premise_data_type, self.db_num, premise_start, premise_size, premise_bit_index
        )
        self.logger.info(f"*** End get premise condition value *** -> real_value: {real_premise_value}, "
                         f"expect_value: {premise_value}")
        if premise_value == real_premise_value:
            return self.plc.execute_read(data_type, self.db_num, start, size, bit_index)
        while time_out:
            count += 1
            time.sleep(1)
            self.logger.info(
                f"*** Start get premise condition value *** -> 第 {count} 次读前提条件值, "
                f"start: {premise_start}, size: {premise_size}, bit_index: {premise_bit_index}"
            )
            real_premise_value = self.plc.execute_read(
                premise_data_type, self.db_num, premise_start, premise_size, premise_bit_index
            )
            self.logger.info(f"*** End get premise condition value *** -> real_value: {real_premise_value}, "
                             f"expect_value: {premise_value}")
            if premise_value == real_premise_value:
                break
            time_out -= 1
            if time_out == 0:
                self.logger.error(f"*** plc 超时 *** -> plc 未在 {expect_time}s 内及时回复, "
                                  f"读取地址位 {start}, data_type: {data_type}, bit_index: {bit_index} 值!")

        return self.plc.execute_read(data_type, self.db_num, start, size, bit_index)

    def save_current_recipe_local(self):
        """保存当前的配方名称."""
        self.config["status_variable"]["current_recipe_name"]["value"] = self.get_sv_value_with_name("current_recipe_name")
        self.update_config(f"{'/'.join(self.__module__.split('.'))}.conf", self.config)

    def save_current_lot_local(self):
        """保存当前lot信息."""
        self.config["status_variable"]["current_point_name"]["value"] = self.get_sv_value_with_name("current_point_name")
        self.config["status_variable"]["current_recipe_name"]["value"] = self.get_sv_value_with_name("current_recipe_name")
        self.config["status_variable"]["current_lot_name"]["value"] = self.get_sv_value_with_name("current_lot_name")
        self.config["status_variable"]["current_lot_article_name"]["value"] = self.get_sv_value_with_name("current_lot_article_name")
        self.config["status_variable"]["current_lot_quality"]["value"] = self.get_sv_value_with_name("current_lot_quality")
        self.config["status_variable"]["current_lot_state"]["value"] = self.get_sv_value_with_name("current_lot_state")

        self.update_config(f"{'/'.join(self.__module__.split('.'))}.conf", self.config)

    def get_callback(self, signal_name: str) -> list:
        """根据 signal_name 获取对应的 callback.

        Args:
            signal_name: 信号名称.

        Returns:
            list: 要执行的操作列表.
        """
        return self.get_config_value("plc_signal_start")[signal_name].get("call_back")

    def get_recipe_id_with_name(self, recipe_name: str) -> int:
        """根据配方名称获取配方id.

        Args:
            recipe_name: 配方名称.

        Returns:
            int: 配方id.
        """
        recipe_instance = self.mysql.query_data_one(Recipe, recipe_name=recipe_name)
        # noinspection PyUnresolvedReferences
        return recipe_instance.recipe_id if recipe_instance else 0

    def get_equipment_state(self) -> str:
        """获取plc状态."""
        if self.plc.get_connect_state():
            if self.get_sv_value_with_name("current_control_state") == 1:
                state = "本地模式"
            else:
                state = "远程模式"
        else:
            state = "离线模式"
        return state

    def get_point_names(self) -> list:
        """获取所有的point配方名称.

        Returns:
            list: 点位配方列表.
        """
        return self.get_dv_value_with_name("point_names")

    def set_clear_alarm(self, alarm_code: int):
        """通过S5F1发送报警和解除报警.

        Args:
            alarm_code (int): 报警code, 2: 报警, 9: 清除报警.
        """
        if alarm_code == 2:
            alarm_id = self.plc.execute_read(
                self.get_address_data_type("alarm_id"), self.db_num, self.get_siemens_start("alarm_id"),
                self.get_siemens_size("alarm_id")
            )
            self.logger.info(f"*** Occur alarm *** -> alarm_id: {alarm_id}")
            try:
                self.current_alarm_id = U4(alarm_id)
            except ValueError:
                self.current_alarm_id = U4(0)
            self.current_alarm_text = self.alarms.get(str(alarm_id)).text if self.alarms.get(str(alarm_id)) else ""

        def _alarm_sender(_alarm_code):
            self.send_and_waitfor_response(
                self.stream_function(5, 1)({
                    "ALCD": _alarm_code, "ALID": self.current_alarm_id, "ALTX": self.current_alarm_text
                })
            )

        threading.Thread(target=_alarm_sender, args=(alarm_code,), daemon=True).start()

    def set_carrier_track_in_reply_info(self):
        """设置进站结果信息."""
        current_point_name = self.get_sv_value_with_name("current_point_name")
        result = self.mysql.query_data_one(Point, point_name=current_point_name)
        # noinspection PyTypeChecker
        result_dict = Point.as_dict(result)
        self.set_dv_value_with_name("carrier_track_in_state", 1)
        self.set_dv_value_with_name("x_point", result_dict.get("x_point", 0))
        self.set_dv_value_with_name("y_point", result_dict.get("y_point", 0))
        self.set_dv_value_with_name("x_mark_point", result_dict.get("x_mark_point", 0))
        self.set_dv_value_with_name("y_mark_point", result_dict.get("y_mark_point", 0))

    def set_dbc_info(self):
        """设置dbc的码和状态."""
        dbc_code_left_list = [f"left_dbc{i}" for i in range(1, 31)]
        dbc_state_left_list = [1 for _ in range(1, 31)]
        self.set_dv_value_with_name("dbc_codes_left", dbc_code_left_list)
        self.set_dv_value_with_name("dbc_states_left", dbc_state_left_list)

        dbc_code_right_list = [f"right_dbc{i}" for i in range(1, 31)]
        dbc_state_right_list = [1 for _ in range(1, 31)]
        self.set_dv_value_with_name("dbc_codes_right", dbc_code_right_list)
        self.set_dv_value_with_name("dbc_states_right", dbc_state_right_list)

    def wait_eap_reply(self, call_back=None):
        """等待EAP回复进站."""
        if call_back.get("local"):
            func_name = call_back.get("func_name")
            getattr(self, func_name)()
