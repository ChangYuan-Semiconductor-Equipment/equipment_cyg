# pylint: skip-file
import copy
import json
import threading
import time
from typing import Union, Optional

from mitsubishi_plc.mitsubishi_plc import MitsubishiPlc
from mitsubishi_plc.exception import PLCReadError, PLCRuntimeError
from secsgem.common import Message
from secsgem.secs import variables, SecsHandler, SecsStreamFunction, data_items
from secsgem.secs.variables import U4, Binary

from equipment_cyg.controller.controller import Controller


class Sputter(Controller):
    """Sputter设备 class."""

    def __init__(self):
        super().__init__()
        self.recipes = self.get_config_value("recipes", {})  # 获取所有上传过的配方信息

        self.current_alarm_id = U4(0)
        self.current_alarm_text = ""
        self.plc = MitsubishiPlc(self.get_dv_value_with_name("plc_ip"), self.get_dv_value_with_name("plc_port"))
        self.plc.logger.addHandler(self.file_handler)  # 保存plc日志到文件

        recipe_name = self.plc.execute_read("str", "D8420", 10)
        self.set_sv_value_with_name("current_recipe_name", recipe_name)
        self.save_current_recipe_local()

        self.enable_equipment()  # 启动MES服务
        self.start_monitor_plc_thread()  # 启动监控plc信号线程

    def start_monitor_plc_thread(self):
        """启动监控 plc 信号的线程."""
        if self.plc.communication_open():
            self.logger.warning(f"*** First connect to plc success *** -> plc地址是: {self.plc.plc_ip}.")
        else:
            self.logger.warning(f"*** First connect to plc failure *** -> plc地址是: {self.plc.plc_ip}.")

        self.machine_state_thread()  # 运行状态线程
        self.bool_signal_thread()  # bool类型信号线程

    def machine_state_thread(self):
        """运行状态变化的线程."""

        def _machine_state():
            """监控运行状态变化."""
            alarm_state = self.get_dv_value_with_name("alarm_state")
            address = self.get_mitsubishi_address("machine_state")
            data_type = self.get_address_data_type("machine_state")
            while True:
                try:
                    machine_state = self.plc.execute_read(data_type, address=address, save_log=False)
                    if machine_state != self.get_sv_value_with_name("current_machine_state"):
                        if machine_state == alarm_state:
                            self.set_clear_alarm(self.get_dv_value_with_name("occur_alarm_code"))
                        elif self.get_sv_value_with_name("current_machine_state") == alarm_state:
                            self.set_clear_alarm(self.get_dv_value_with_name("clear_alarm_code"))
                        self.set_sv_value_with_name("current_machine_state", machine_state)
                        self.send_s6f11("machine_state_change")
                        self.save_current_machine_state_local()
                except PLCReadError as e:
                    self.logger.warning(f"*** Read failure: machine_state *** -> reason: {str(e)}!")
                    time.sleep(self.get_dv_value_with_name("reconnect_plc_wait_time"))

        threading.Thread(target=_machine_state, daemon=True, name="machine_state_thread").start()

    def set_clear_alarm(self, alarm_code: int):
        """通过S5F1发送报警和解除报警.

        Args:
            alarm_code (int): 报警code, 2: 报警, 9: 清除报警.
        """
        if alarm_code == self.get_dv_value_with_name("occur_alarm_code"):
            alarm_list = self.plc.execute_read(
                self.get_address_data_type("alarm"), self.get_mitsubishi_address("alarm"),
                length=self.get_mitsubishi_address_size("alarm")
            )
            alarm_id = self.get_alarm_id(alarm_list)
            self.logger.info(f"*** Occur alarm *** -> alarm_id: {alarm_id}")
            if alarm_id and str(alarm_id) in self.alarms:
                alarm_text = self.alarms.get(str(alarm_id)).text
            else:
                alarm_text = "Occur Alarm, but alarm is not defined in alarm csv file."
            self.current_alarm_id = U4(alarm_id)
            self.current_alarm_text = alarm_text

        def _alarm_sender(_alarm_code):
            self.send_and_waitfor_response(
                self.stream_function(5, 1)({
                    "ALCD": _alarm_code, "ALID": self.current_alarm_id, "ALTX": self.current_alarm_text
                })
            )
        threading.Thread(target=_alarm_sender, args=(alarm_code,), daemon=True).start()

    @staticmethod
    def get_alarm_id(alarm_list: list):
        """获取报警id.

        Args:
            alarm_list: 报警列表.

        Returns:
            int: 报警id.
        """
        if True in alarm_list:
            return alarm_list.index(True) + 1
        return 0

    def bool_signal_thread(self):
        """bool 类型信号的线程."""

        def _bool_signal(**kwargs):
            """监控 plc bool 信号."""
            self.monitor_plc_address(**kwargs)  # 实时监控plc信号

        plc_signal_dict = self.get_config_value("plc_signal_start", {})
        for signal_name, signal_info in plc_signal_dict.items():
            if isinstance(signal_info, dict) and signal_info.get("loop", False):  # 实时监控的信号才会创建线程
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
                current_value = self.plc.execute_read(kwargs.get("data_type"), kwargs.get("start"), save_log=False)
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
        self.logger.info(f"{'=' * 40} 得到信号: {signal_info.get('description')}, 地址位: {signal_info.get('start')} {'=' * 40}")
        self.execute_call_backs(call_back_list)  # 根据配置文件下的call_back执行具体的操作
        self.logger.info(f"{'=' * 40} 信号清除: {signal_info.get('description')} {'=' * 40}")

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
            "read_recipe_info": self.read_recipe_info
        }
        for i, call_back in enumerate(call_backs, 1):
            self.logger.info(f"{'-' * 30} Step {i} 开始: {call_back.get('description')} {'-' * 30}")
            operation_func = operation_func_map.get(call_back.get("operation_type"))
            # noinspection PyArgumentList
            operation_func(call_back=call_back)
            self.is_send_event(call_back)
            self.logger.info(f"{'-' * 30} 结束 Success: {call_back.get('description')} {'-' * 30}")

    def get_recipe_values(self, recipe_info_list: list):
        """获取配方信息.

        Args:
            recipe_info_list (list): 配方信息列表.
        """
        recipe_info_result = {}
        for recipe_info in recipe_info_list:
            name = recipe_info.get("name")
            start = recipe_info.get("start")
            data_type = recipe_info.get("data_type")
            size = recipe_info.get("size", 1)
            scale = recipe_info.get("scale", 1)
            recipe_value = self.plc.execute_read(data_type, start, None if size == 1 else size)
            if data_type != "str":
                recipe_info_result.update({name: recipe_value * scale})
            else:
                recipe_info_result.update({name: recipe_value})
        return recipe_info_result

    # noinspection PyUnusedLocal
    def read_recipe_info(self, call_back: dict):
        """读取配方信息.

        Args:
            call_back (dict): 读取配方信息的配置信息.
        """
        recipe_id = self.plc.execute_read("int16", "D8405")
        recipe_name = self.plc.execute_read("str", "D8420", 10)
        self.set_dv_value_with_name("update_recipe_name", recipe_name)
        recipe_id_name = f"{recipe_id}_{recipe_name}"
        self.recipes.update({recipe_id_name: {"CHB1-2": {}}})

        recipe_info_chb1_list = self.get_config_value("recipe_info_chb12", parent_name="plc_signal_start")
        chb1_2_recipe_info = self.get_recipe_values(recipe_info_chb1_list)
        self.recipes[recipe_id_name].update({"CHB1-2": chb1_2_recipe_info})

        layer_interval = 48
        recipe_info_layer_list = self.get_config_value("recipe_info_layer", parent_name="plc_signal_start")

        for i in range(1, 11):
            layer_name = f"layer{i}"
            real_recipe_info_layer_list = self.get_real_recipe_info_layer_list(recipe_info_layer_list, layer_interval, i)
            layer_recipe_info = self.get_recipe_values(real_recipe_info_layer_list)
            self.recipes[recipe_id_name].update({layer_name: layer_recipe_info})
        self.save_recipe_info()

    @staticmethod
    def get_real_recipe_info_layer_list(recipe_info_list: list, interval: int, index: int):
        """获取真实的配方信息列表.

        Args:
            recipe_info_list: 配方信息列表.
            interval: 间隔.
            index: 索引

        Returns:
            list: 真实的配方信息列表.
        """
        recipe_info_list_copy = copy.deepcopy(recipe_info_list)
        for i, recipe_info in enumerate(recipe_info_list):
            origin_start_int = int(recipe_info["start"][1::])
            real_start = f"D{origin_start_int + (index - 1) * interval}"
            recipe_info_list_copy[i]["start"] = real_start
        return recipe_info_list_copy

    def save_recipe_info(self):
        """保存配方信息."""
        self.config["recipes"] = self.recipes
        self.update_config(f"{'/'.join(self.__module__.split('.'))}.conf", self.config)

    def read_operation_update_sv_or_dv(self, call_back: dict):
        """读取 plc 数据, 更新sv.

        Args:
            call_back (dict): 读取地址位的信息.
        """
        start, data_type, size = call_back.get("start"), call_back.get("data_type"), call_back.get("size", 1)
        # 先判断有木有前提条件
        if premise_start := call_back.get("premise_start"):
            plc_value = self.read_with_condition(
                start, premise_start,
                data_type, call_back.get("premise_data_type"),
                call_back.get("premise_value"), time_out=call_back.get("premise_time_out", 5)
            )
        else:
            # 直接读取
            plc_value = self.plc.execute_read(data_type, start, length=size)

        if dv_name := call_back.get("dv_name"):
            self.set_dv_value_with_name(dv_name, plc_value)
        elif sv_name := call_back.get("sv_name"):
            self.set_sv_value_with_name(sv_name, plc_value)

    def read_with_condition(
            self, start: str, premise_start: str, data_type: str,
            premise_data_type: str, premise_value: Union[int, bool, str, float], time_out=180) -> Union[str, int, bool, float, list]:
        """根据条件信号读取指定地址位的值.

        Args:
            start (str): 要读取地址位的起始位.
            premise_start (str): 前提条件地址位的起始位.
            data_type (str): 要读取数据类型.
            premise_data_type (str): 前提条件数据类型.
            premise_value (Union[int, bool, str, float]): 前提条件的值.
            time_out (int): 超时时间.

        Returns:
            Union[str, int, bool, float, list]: 返回去读地址的值.
        """
        self.read_condition_value(premise_start, premise_data_type, premise_value, time_out)
        return self.plc.execute_read(data_type, start)

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

    def write_operation(self, call_back: dict):
        """向 plc 地址位写入数据.

        Args:
            call_back (dict): 要写入值的地址位信息.
        """
        start, data_type, size = call_back.get("start"), call_back.get("data_type"), call_back.get("size", 1)
        write_value = self.get_real_write_value(call_back.get("value"))

        # 先判断有木有前提条件
        if premise_start := call_back.get("premise_start"):
            self.write_with_condition(
                start, premise_start, call_back.get("data_type"), call_back.get("premise_data_type"),
                call_back.get("premise_value"), write_value, size,call_back.get("premise_time_out", 5)
            )
            return

        # 没有前提条件, 直接写入
        self.plc.execute_write(data_type, start, write_value)

        # 判断有木有写入成功, 如果没成功再次写入直到写入成功
        self.is_write_success(data_type, start, write_value, size)

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

    def write_with_condition(
            self, start: str, premise_start: str, data_type: str, premise_data_type: str,
            premise_value: Union[bool, int, float, str], write_value: Union[bool, int, float, str], size: int, time_out: int):
        """Write value with condition.

        Args:
            start: 要清空信号的地址位置.
            premise_start: 前提条件信号的地址位置.
            data_type: 要写入数据类型.
            premise_data_type: 前提条件数据类型.
            premise_value: 清空地址的判断值.
            write_value: 要写入的数据.
            size: 要写入的数据长度.
            time_out: 超时时间.
        """
        self.read_condition_value(premise_start, premise_data_type, premise_value, time_out)
        self.plc.execute_write(data_type, start, write_value)
        self.is_write_success(data_type, start, write_value, size)

    def is_write_success(self, data_type: str, start: str, write_value: Union[int, float, bool, str], size: int):
        """判断写入是否成功."""
        count = 1
        while self.plc.execute_read(data_type, start) != write_value:
            self.logger.warning(
                f"*** 第 {count} 次写入失败 *** -> 地址位: {start}, 类型: {data_type}, length: {size}, 写入值: {write_value}"
            )
            self.plc.execute_write(data_type, start, write_value)

    def is_send_event(self, call_back):
        """判断是否要发送事件."""
        if (event_name := call_back.get("event_name")) in self.get_config_value("collection_events"):  # 触发事件
            self.send_s6f11(event_name)

    def save_current_recipe_local(self):
        """保存当前配方到本地."""
        recipe_name = self.get_sv_value_with_name("current_recipe_name")
        self.config["status_variable"]["current_recipe_name"]["value"] = recipe_name
        self.update_config(f"{'/'.join(self.__module__.split('.'))}.conf", self.config)

    def save_current_machine_state_local(self):
        """保存当前配方到本地."""
        current_machine_state = self.get_sv_value_with_name("current_machine_state")
        self.config["status_variable"]["current_recipe_name"]["value"] = current_machine_state
        self.update_config(f"{'/'.join(self.__module__.split('.'))}.conf", self.config)

    def get_callback(self, signal_name: str) -> list:
        """根据 signal_name 获取对应的 callback.

        Args:
            signal_name: 信号名称.

        Returns:
            list: 要执行的操作列表.
        """
        return self.get_config_value("plc_signal_start")[signal_name].get("call_back")

    def update_sv_value(self, signal_name: str):
        """更新sv value.

        Args:
            signal_name: 信号名称.
        """
        signal_dict = self.get_config_value(signal_name, parent_name="plc_signal_start")
        start_address = signal_dict.get("start")
        interval = signal_dict.get("interval")
        data_type = signal_dict.get("data_type")
        scale = signal_dict.get("scale", 1)
        count = signal_dict.get("count")
        sv_id_start = signal_dict.get("sv_id_start")
        for i in range(1, count + 1):
            sv_name = self.get_sv_name_with_id(sv_id_start + i - 1)
            address = f"{start_address[0]}{int(start_address[1:]) + (i - 1) * interval}"
            sv_value = self.plc.execute_read(data_type, address)
            self.set_sv_value_with_name(sv_name, round(sv_value * scale, 2))

    def update_sv_value_other(self):
        """更新其他sv value."""
        scale_list = (3 * [0.01] + [1] + 4 * [0.01] + 4 * [1] + [0.1] + [1] + 2 * [0.1] + 6 * [1]
                      + 22 * [0.01] + 11 * [1] + 11 * [0.01] + 21 * [1] + [0.1] + [1] + [0.1] + [1]
                      + 3 * [0.1] + [1] + 2 * [0.1])
        signal_dict = self.get_config_value("other_sv", parent_name="plc_signal_start")
        start = signal_dict.get("start")
        sv_id_start = signal_dict.get("sv_id_start")
        length = signal_dict.get("count")
        value_list = self.plc.execute_read("int16", start, length=length)
        value_list_length = len(value_list)
        self.logger.info("读取plc数据长度是: %s, 期望长度是: %s", value_list_length, length)
        for i, value in enumerate(value_list):
            sv_name = self.get_sv_name_with_id(i + sv_id_start)
            self.set_sv_value_with_name(sv_name, round(int(value) * scale_list[i], 2))

    def _on_s01f03(self, handler: SecsHandler, message: Message) -> SecsStreamFunction | None:
        """Handle Stream 1, Function 3, Equipment status request.

        Args:
            handler: handler the message was received on
            message: complete message received

        """
        del handler  # unused parameters

        self.update_sv_value("target_life_measured")
        self.update_sv_value("chb3_spt_state")
        self.update_sv_value_other()

        function = self.settings.streams_functions.decode(message)

        responses = []

        if len(function) == 0:
            responses = [self._get_sv_value(status_variable) for status_variable in self._status_variables.values()]
        else:
            for status_variable_id in function:
                if status_variable_id not in self._status_variables:
                    responses.append(variables.Array(data_items.SV, []))
                else:
                    status_variable = self._status_variables[status_variable_id]
                    responses.append(self._get_sv_value(status_variable))

        return self.stream_function(1, 4)(responses)

    def _on_s07f05(self, handler, packet):
        """host请求配方数据."""
        del handler
        recipe_name = self.get_receive_data(packet)
        recipe_id_name = self.get_recipe_id_name(recipe_name, self.recipes)
        pp_body = json.dumps(self.recipes.get(recipe_id_name, ""))
        pp_body_b = Binary(pp_body)
        return self.stream_function(7, 6)([recipe_name, pp_body_b])

    def _on_s07f19(self, handler, packet):
        """Host查看设备的所有配方."""
        del handler
        recipe_id_names = list(self.recipes.keys())
        recipe_names = [recipe_id_name.split("_", 1)[-1] for recipe_id_name in recipe_id_names]
        return self.stream_function(7, 20)(recipe_names)

    def _on_s07f25(self, handler, packet):
        """host请求格式化配方信息."""
        del handler
        recipe_name = self.get_receive_data(packet)
        recipe_id_name = self.get_recipe_id_name(recipe_name, self.recipes)
        recipe_info = self.recipes.get(recipe_id_name)
        ccode_list = []
        for code, param_value_dict in recipe_info.items():
            result = [f"{param}_{value}" for param, value in param_value_dict.items()]
            ccode_list.append({"CCODE": code, "PPARM": result})
        return self.stream_function(7, 26)({
            "PPID": recipe_name, "MDLN": self.model_name, "SOFTREV": self.software_version, "CCODE": ccode_list
        })

    def _on_rcmd_pp_select(self, recipe_name: str):
        """Host发送s02f41配方切换.

        Args:
            recipe_name (str): 要切换的配方name.
        """
        recipe_id_name = self.get_recipe_id_name(recipe_name, self.recipes)
        recipe_id, recipe_name = recipe_id_name.split("_")
        self.set_dv_value_with_name("pp_select_recipe_id", int(recipe_id))
        self.set_dv_value_with_name("pp_select_recipe_name", recipe_name)

        self.execute_call_backs(self.get_callback("pp_select"))

        # 切换成功, 更新当前配方id_name, 保存当前配方
        if self.get_dv_value_with_name("pp_select_state") == self.get_dv_value_with_name("pp_select_success_state"):
            self.set_sv_value_with_name("current_recipe_name", recipe_name)
            self.save_current_recipe_local()

        self.send_s6f11("pp_select")  # 触发 pp_select 事件

    def _on_rcmd_control_equipment(self, control_type: int):
        """Host发送s02f41 控制设备暂停 停止 启动.

        Args:
            control_type: 控制类型, 1: Start, 2: Stop, 3: Pause.
        """
        self.logger.info("*** 先将控制状态清空 ***")
        self.plc.execute_write("int16", "D8407", 0)
        value = self.plc.execute_read("int16", "D8407")
        self.logger.info("*** 控制状态清空成功 *** -> 状态应该是0, value: %s", value)
        self.set_dv_value_with_name("control_type", int(control_type))
        self.execute_call_backs(self.get_callback("control_equipment"))
