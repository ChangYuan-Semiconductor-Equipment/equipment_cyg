# pylint: skip-file
"""SMK 下料设备."""
import threading
import time
from typing import Union

from modbus_api.exception import PLCWriteError, PLCReadError, PLCRuntimeError
from modbus_api.modbus_api import ModbusApi

from equipment_cyg.controller.controller import Controller


# noinspection DuplicatedCode
class SmkCutting(Controller):  # pylint: disable=R0901
    """SmkCutting class."""

    def __init__(self):
        super().__init__()
        self.plc = ModbusApi(self.get_dv_value_with_name("plc_ip"))
        self.plc.logger.addHandler(self.file_handler)  # 保存plc日志到文件

        self.enable_equipment()  # 启动MES服务

        self.start_monitor_plc_thread()  # 启动监控plc信号线程

    def start_monitor_plc_thread(self):
        """启动监控 plc 信号的线程."""
        if self.plc.communication_open():
            self.logger.warning(f"*** First connect to plc success *** -> plc地址是: {self.plc.ip}.")
        else:
            self.logger.warning(f"*** First connect to plc failure *** -> plc地址是: {self.plc.ip}.")

        self.mes_heart_thread()  # 心跳线程
        self.control_state_thread()  # 控制状态线程
        self.machine_state_thread()  # 运行状态线程
        self.bool_signal_thread()  # bool类型信号线程

    def mes_heart_thread(self):
        """mes 心跳的线程."""

        def _mes_heart():
            """mes 心跳, 每隔 2s 写入一次."""
            start, bit_index = self.get_modbus_start("mes_heart"), self.get_modbus_bit_index("mes_heart")
            while True:
                try:
                    self.plc.execute_write("bool", start, True, bit_index, save_log=False)
                    time.sleep(self.get_config_value("mes_heart_time"))
                    self.plc.execute_write("bool", start, False, bit_index, save_log=False)
                    time.sleep(self.get_config_value("mes_heart_time"))
                except PLCWriteError as e:
                    self.set_sv_value_with_name("current_control_state", 0)

                    self.logger.warning(f"*** Write failure: mes_heart *** -> reason: {str(e)}!")
                    if self.plc.communication_open() is False:
                        wait_time = self.get_dv_value_with_name("reconnect_plc_wait_time")
                        self.logger.warning(f"*** Plc connect attempt *** -> wait {wait_time}s attempt connect again.")
                        time.sleep(wait_time)
                    else:
                        self.logger.warning(f"*** After exception plc connect success *** -> plc地址是: {self.plc.ip}.")

        threading.Thread(target=_mes_heart, daemon=True, name="mes_heart_thread").start()

    def control_state_thread(self):
        """控制状态变化的线程."""

        def _control_state():
            """监控控制状态变化."""
            start, bit_index = self.get_modbus_start("control_state"), self.get_modbus_bit_index("control_state")
            data_type = self.get_modbus_data_type("control_state")
            while True:
                try:
                    control_state = 1 if self.plc.execute_read(data_type, start, bit_index, save_log=False) else 2
                    if control_state != self.get_sv_value_with_name("current_control_state"):
                        self.set_sv_value_with_name("current_control_state", control_state)
                        self.send_s6f11("control_state_change")
                except PLCReadError as e:
                    self.logger.warning(f"*** Read failure: control_state *** -> reason: {str(e)}!")
                    time.sleep(self.get_dv_value_with_name("reconnect_plc_wait_time"))

        threading.Thread(target=_control_state, daemon=True, name="control_state_thread").start()

    def machine_state_thread(self):
        """运行状态变化的线程."""

        def _machine_state():
            """监控运行状态变化."""
            start, data_type = self.get_modbus_start("machine_state"), self.get_modbus_data_type("machine_state")
            while True:
                try:
                    machine_state = self.plc.execute_read(data_type, start, save_log=False)
                    if machine_state != self.get_sv_value_with_name("current_machine_state"):
                        self.set_sv_value_with_name("current_machine_state", machine_state)
                        self.send_s6f11("machine_state_change")
                except PLCReadError as e:
                    self.logger.warning(f"*** Read failure: machine_state *** -> reason: {str(e)}!")
                    time.sleep(self.get_dv_value_with_name("reconnect_plc_wait_time"))

        threading.Thread(target=_machine_state, daemon=True, name="machine_state_thread").start()

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
                start, bit_index =  kwargs.get("start"),  kwargs.get("bit_index")
                current_value = self.plc.execute_read("bool", start, bit_index=bit_index, save_log=False)
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
                         f"地址位: {signal_info.get('start')} {'=' * 40}")

        self.execute_call_backs(call_back_list)  # 根据配置文件下的call_back执行具体的操作

        self.logger.info(f"{'=' * 40} Signal clear: {signal_info.get('description')} {'=' * 40}")

    @Controller.try_except_exception(PLCRuntimeError("*** Execute call backs error ***"))
    def execute_call_backs(self, call_backs: list, time_out=180):
        """根据操作列表执行具体的操作.

        Args:
            call_backs (list): 要执行动作的信息列表, 按照列表顺序执行.
            time_out (int): 超时时间.

        Raises:
            PLCRuntimeError: 在执行配置文件下的步骤时出现异常.
        """
        # noinspection PyTypeChecker
        operation_func_map = {
            "read": self.read_operation_update_sv_or_dv,
            "write": self.write_operation
        }
        for i, call_back in enumerate(call_backs, 1):
            self.logger.info(f"{'-' * 30} Step {i} 开始: {call_back.get('description')} {'-' * 30}")
            operation_func = operation_func_map.get(call_back.get("operation_type"))
            # noinspection PyArgumentList
            operation_func(call_back=call_back, time_out=time_out)
            self.is_send_event(call_back)
            self.logger.info(f"{'-' * 30} 结束 Success: {call_back.get('description')} {'-' * 30}")

    def is_send_event(self, call_back):
        """判断是否要发送事件."""
        if (event_name := call_back.get("event_name")) in self.get_config_value("collection_events"):  # 触发事件
            self.send_s6f11(event_name)

    def write_operation(self, call_back: dict):
        """向 plc 地址位写入数据.

        Args:
            call_back (dict): 要写入值的地址位信息.
        """
        start, data_type, size = call_back.get("start"), call_back.get("data_type"), call_back.get("size", 1)
        write_value = call_back.get("value")

        # 先判断有木有前提条件
        if premise_start := call_back.get("premise_start"):
            self.write_with_condition(
                start, premise_start, call_back.get("data_type"), call_back.get("premise_data_type"),
                call_back.get("premise_value"), write_value, call_back.get("premise_time_out", 5)
            )
            return

        # 没有前提条件, 直接写入
        self.plc.execute_write(data_type, start, write_value)

    def write_with_condition(
            self, start: str, premise_start: str, data_type: str, premise_data_type: str,
            premise_value: Union[bool, int, float, str], write_value: Union[bool, int, float, str], time_out: int):
        """Write value with condition.

        Args:
            start: 要清空信号的地址位置.
            premise_start: 前提条件信号的地址位置.
            data_type: 要写入数据类型.
            premise_data_type: 前提条件数据类型.
            premise_value: 清空地址的判断值.
            write_value: 要写入的数据.
            time_out: 超时时间.
        """
        self.read_condition_value(premise_start, premise_data_type, premise_value, time_out)
        self.plc.execute_write(data_type, start, write_value)

    def read_operation_update_sv_or_dv(self, call_back: dict):
        """读取 plc 数据, 更新sv.

        Args:
            call_back (dict): 读取地址位的信息.
        """
        start, data_type, size = call_back.get("start"), call_back.get("data_type"), call_back.get("size", 1)
        plc_value = self.plc.execute_read(data_type, start, count=size)
        if dv_name := call_back.get("dv_name"):
            self.set_dv_value_with_name(dv_name, plc_value)
        elif sv_name := call_back.get("sv_name"):
            self.set_sv_value_with_name(sv_name, plc_value)

    def read_condition_value(
            self, premise_start: str, premise_data_type: str, premise_value: Union[int, bool], time_out: int):
        """读取条件值.

        Args:
            premise_start: 前提条件信号的地址位置.
            premise_data_type: 前提条件数据类型.
            premise_value: 前提条件的值.
            time_out: 超时时间.
        """
        count = 1
        real_premise_value = self.plc.execute_read(premise_data_type, premise_start)
        self.logger.info(f"*** 第 %s 次读取前提值 *** 实际值: %s, 期待值: %s", count, real_premise_value, premise_value)
        while self.plc.execute_read(premise_data_type, premise_start) != premise_value:
            count += 1
            time_out -= 1
            time.sleep(1)
            real_premise_value = self.plc.execute_read(premise_data_type, premise_start)
            self.logger.info(f"*** 第 %s 次读取前提值 *** 实际值: %s, 期待值: %s", count, real_premise_value, premise_value)
            if time_out == 0:
                self.logger.error(f"*** plc 超时 *** -> plc 未在 {time_out}s 内及时回复")
                break
