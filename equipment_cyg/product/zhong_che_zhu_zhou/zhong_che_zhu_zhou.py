# pylint: skip-file
"""中车株洲拨针设备."""
import threading
import time
from typing import Union

from inovance_tag.exception import PLCWriteError, PLCReadError, PLCRuntimeError
from inovance_tag.tag_communication import TagCommunication
from inovance_tag.tag_type_enum import TagTypeEnum
from secsgem.gem import StatusVariable
from secsgem.secs.data_items import ACKC10
from secsgem.secs.variables import I4, Base, Array, U4
from equipment_cyg.controller.controller import Controller


# noinspection DuplicatedCode
class ZhongCheZhuZhou(Controller):
    """中车株洲class."""
    def __init__(self):
        super().__init__()
        self.alarm_id = I4(0)  # 保存报警id
        self.alarm_text = ""  # 保存报警内容

        self.load_current_recipe()  # 断电重启后加载断电前的配方

        self.plc_in = TagCommunication(self.get_config_value("plc_ip_in"))
        self.plc_in.logger.addHandler(self.file_handler)  # 保存plc日志到文件

        self.plc_st1020 = TagCommunication(self.get_config_value("plc_ip_st1020"))
        self.plc_st1020.logger.addHandler(self.file_handler)  # 保存plc日志到文件

        self.plc_st1021 = TagCommunication(self.get_config_value("plc_ip_st1021"))
        self.plc_st1021.logger.addHandler(self.file_handler)  # 保存plc日志到文件

        self.plc_st1022 = TagCommunication(self.get_config_value("plc_ip_st1022"))
        self.plc_st1022.logger.addHandler(self.file_handler)  # 保存plc日志到文件

        self.enable_equipment()  # 启动MES服务

        self.start_monitor_plc_thread()  # 启动监控plc信号线程

    def load_current_recipe(self):
        """断电重启后加载断电前的配方"""
        self.set_sv_value_with_name(
            "current_recipe_id_name_in", self.get_config_value("current_recipe_id_name_in", default="")
        )
        self.set_sv_value_with_name(
            "current_recipe_id_name_st1020", self.get_config_value("current_recipe_id_name_st1020", default="")
        )
        self.set_sv_value_with_name(
            "current_recipe_id_name_st1021", self.get_config_value("current_recipe_id_name_st1021", default="")
        )
        self.set_sv_value_with_name(
            "current_recipe_id_name_st1022", self.get_config_value("current_recipe_id_name_st1022", default="")
        )

    def start_monitor_plc_thread(self):
        """启动监控 plc 信号的线程."""
        self.connect_plc(self.plc_in)
        self.connect_plc(self.plc_st1020)
        self.connect_plc(self.plc_st1021)
        self.connect_plc(self.plc_st1022)
        self.mes_heart_thread(self.plc_in)  # 进站plc心跳线程
        self.mes_heart_thread(self.plc_st1020)  # st1020出站plc心跳线程
        self.mes_heart_thread(self.plc_st1021)  # st1021出站plc心跳线程
        self.mes_heart_thread(self.plc_st1022)  # st1022出站plc心跳线程
        self.control_state_thread("in")  # 进站plc控制状态线程
        self.control_state_thread("st1020")  # st1020出站plc控制状态线程
        self.control_state_thread("st1021")  # st1021出站plc控制状态线程
        self.control_state_thread("st1022")  # st1022出站plc控制状态线程
        self.machine_state_thread("in")  # 进站plc运行状态线程
        self.machine_state_thread("st1020")  # st1020出站plc运行状态线程
        self.machine_state_thread("st1021")  # st1021出站plc运行状态线程
        self.machine_state_thread("st1022")  # st1022出站plc运行状态线程
        self.bool_signal_thread("in")  # bool类型信号线程
        self.bool_signal_thread("st1020")  # bool类型信号线程
        self.bool_signal_thread("st1021")  # bool类型信号线程
        self.bool_signal_thread("st1022")  # bool类型信号线程

    def connect_plc(self, plc_instance: TagCommunication):
        """连接plc.

        Args:
            plc_instance (TagCommunication): plc 标签通讯实例.
        """
        if plc_instance.communication_open():
            self.logger.warning(f"*** First connect to plc success *** -> plc地址是: {plc_instance.ip}.")
        else:
            self.logger.warning(f"*** First connect to plc failure *** -> plc地址是: {plc_instance.ip}.")

    def mes_heart_thread(self, plc_instance: TagCommunication):
        """mes 心跳的线程.

        Args:
            plc_instance (TagCommunication): plc 标签通讯实例.
        """
        def _mes_heart(_plc_instance):
            """mes 心跳, 每隔 2s 写入一次."""
            tag_name = self.get_tag_name("mes_heart")
            while True:
                try:
                    _plc_instance.execute_write(tag_name, TagTypeEnum.BOOL.value, True, save_log=False)
                    time.sleep(self.get_config_value("mes_heart_time"))
                    _plc_instance.execute_write(tag_name, TagTypeEnum.BOOL.value, False, save_log=False)
                    time.sleep(self.get_config_value("mes_heart_time"))
                except PLCWriteError as e:
                    self.logger.warning(f"*** Write failure: mes_heart *** -> reason: {str(e)}!")
                    if _plc_instance.communication_open() is False:
                        wait_time = self.get_config_value("wait_time_plc_disconnect")
                        self.logger.warning(f"*** Plc connect attempt *** -> wait {wait_time}s attempt connect again.")
                        time.sleep(wait_time)
                    else:
                        self.logger.warning(f"*** After exception plc connect success *** "
                                            f"-> plc地址是: {_plc_instance.ip}.")
        threading.Thread(
            target=_mes_heart, args=(plc_instance,), daemon=True, name=f"mes_heart_thread_{plc_instance.ip}"
        ).start()

    def control_state_thread(self, plc_name: str):
        """控制状态变化的线程.

        Args:
            plc_name (str): plc 名称.
        """
        plc_instance = self.get_plc_instance(plc_name)

        def _control_state(_plc_instance):
            """监控控制状态变化."""
            tag_name = self.get_tag_name("control_state")
            while True:
                try:
                    control_state = _plc_instance.execute_read(tag_name, TagTypeEnum.INT.value, save_log=False)
                    current_control_state_name = self.get_real_sv_name("current_control_state", _plc_instance)
                    if control_state != self.get_sv_value_with_name(current_control_state_name):
                        self.set_sv_value_with_name(current_control_state_name, control_state)
                        self.send_s6f11(self.get_real_event_name("control_state_change"))
                except PLCReadError as e:
                    self.logger.warning(f"*** Read failure: control_state *** -> reason: {str(e)}!")
                    time.sleep(self.get_config_value("wait_time_plc_disconnect"))
        threading.Thread(
            target=_control_state, daemon=True, args=(plc_instance,), name=f"control_state_thread_{plc_name}"
        ).start()

    def machine_state_thread(self, plc_name):
        """运行状态变化的线程.

        Args:
            plc_name (str): plc 名称.
        """
        plc_instance = self.get_plc_instance(plc_name)

        def _machine_state(_plc_instance):
            """监控运行状态变化."""
            tag_name = self.get_tag_name("machine_state")
            while True:
                try:
                    machine_state = _plc_instance.execute_read(tag_name, TagTypeEnum.INT.value, save_log=False)
                    current_machine_state_name = self.get_real_sv_name("current_machine_state", _plc_instance)
                    if machine_state != self.get_sv_value_with_name(current_machine_state_name):
                        alarm_state = self.get_config_value("alarm_state")
                        if machine_state == alarm_state:
                            self.set_clear_alarm(2, _plc_instance)
                        elif self.get_sv_value_with_name(current_machine_state_name) == alarm_state:
                            self.set_clear_alarm(self.get_config_value("reset_alarm_code"), plc_instance)
                        self.set_sv_value_with_name(current_machine_state_name, machine_state)
                        self.send_s6f11(self.get_real_event_name("machine_state_change"))
                except PLCReadError as e:
                    self.logger.warning(f"*** Read failure: machine_state *** -> reason: {str(e)}!")
                    time.sleep(self.get_config_value("wait_time_plc_disconnect"))
        threading.Thread(
            target=_machine_state, daemon=True, args=(plc_instance,), name=f"machine_state_thread_{plc_name}"
        ).start()

    def bool_signal_thread(self, plc_name: str):
        """bool 类型信号的线程."""
        plc_instance = self.get_plc_instance(plc_name)

        def _bool_signal(_plc_instance, **kwargs):
            """监控 plc bool 信号."""
            self.monitor_plc_address(_plc_instance, **kwargs)  # 实时监控plc信号

        plc_signal_dict = self.get_config_value("plc_signal_tag_name", {})
        for signal_name, signal_info in plc_signal_dict.items():
            if signal_info.get("loop", False):  # 实时监控的信号才会创建线程
                threading.Thread(
                    target=_bool_signal, daemon=True, args=(plc_instance,), kwargs=signal_info,
                    name=f"{signal_name}_thread_{plc_name}"
                ).start()

    def monitor_plc_address(self, plc_instance: TagCommunication, wait_time=0, **kwargs):
        """实时监控plc信号.

        Args:
            plc_instance (TagCommunication): plc 标签通讯实例.
            wait_time (int): 监控信号的时间间隔, 默认实时监控.
        """
        while True:
            # noinspection PyBroadException
            try:
                current_value = plc_instance.execute_read(kwargs.get("tag_name"), TagTypeEnum.BOOL.value, False)
                current_value and self.signal_trigger_event(kwargs.get("call_back"), kwargs, plc_instance=plc_instance)
                time.sleep(wait_time)
            except Exception:
                pass  # 出现任何异常不做处理

    def signal_trigger_event(self, call_back_list: list, signal_info: dict, plc_instance: TagCommunication = None):
        """监控到信号触发事件.

        Args:
            call_back_list (list): 要执行的操作信息列表.
            signal_info (dict): 信号信息.
            plc_instance: plc_instance.
        """
        self.logger.info(f"{'=' * 40} Get Signal: {signal_info.get('description')}, "
                         f"地址位: {signal_info.get('tag_name')} {'=' * 40}")
        if signal_info.get('description') == "产品进站":
            self.set_sv_value_with_name("track_in_reply_flag", False)
        self.execute_call_backs(call_back_list, plc_instance)  # 根据配置文件下的call_back执行具体的操作

        self.logger.info(f"{'=' * 40} Signal clear: {signal_info.get('description')} {'=' * 40}")

    # noinspection PyUnusedLocal
    def wait_eap_reply(self, call_back=None, **kwargs):
        """等待EAP回复进站."""

        time_out = call_back.get("time_out", 360000)
        wait_time = 1
        while not self.get_sv_value_with_name("track_in_reply_flag"):
            wait_time += 1
            time_out -= 1
            time.sleep(1)
            self.logger.warning("*** 等待 EAP 进站回复 *** -> 已等待 %s 秒", wait_time)

            if time_out == 0:
                self.logger.warning("*** EAP 回复超时 *** -> EAP 未在规定时间内回复进站.")

    def save_recipe(self, **kwargs):
        """保存plc上传的配方."""
        self.config["recipes"].update({
            self.get_sv_value_with_name(self.get_real_sv_name(f"upload_recipe_id", kwargs.get("plc_instance"))): {}
        })
        self.update_config(f"{'/'.join(self.__module__.split('.'))}.conf", self.config)

    @Controller.try_except_exception(PLCRuntimeError("*** Execute call backs error ***"))
    def execute_call_backs(self, call_backs: list, plc_instance: TagCommunication):
        """根据操作列表执行具体的操作.

        Args:
            call_backs (list): 要执行动作的信息列表, 按照列表顺序执行.
            plc_instance (str): 执行callback的plc名称.

        Raises:
            PLCRuntimeError: 在执行配置文件下的步骤时出现异常.
        """
        # noinspection PyTypeChecker
        operation_func_map = {
            "read": self.read_operation_update_sv,
            "write": self.write_operation,
            "wait_eap_reply": self.wait_eap_reply,
            "save_recipe": self.save_recipe
        }
        for i, call_back in enumerate(call_backs, 1):
            self.logger.info(f"{'-' * 30} Step {i} 开始: {call_back.get('description')} {'-' * 30}")
            operation_func = operation_func_map.get(call_back.get("operation_type"))
            # noinspection PyArgumentList
            operation_func(call_back=call_back, plc_instance=plc_instance)
            if call_back.get("event_name"):
                self.is_send_event(call_back, plc_instance)
            self.logger.info(f"{'-' * 30} 结束 Success: {call_back.get('description')} {'-' * 30}")

    def is_send_event(self, call_back, plc_instance: TagCommunication):
        """判断是否要发送事件."""
        origin_event_name = call_back.get("event_name")
        if origin_event_name == "track_in":
            real_event_name = origin_event_name
        else:
            real_event_name = call_back.get("event_name") + f"_{self.get_plc_name(plc_instance)}"
        if real_event_name in self.get_config_value("collection_events"):  # 触发事件
            self.send_s6f11(real_event_name)

    def get_plc_instance(self, plc_name: str) -> TagCommunication:
        """根据plc名称获取plc标签实例.

        Args:
            plc_name (str): plc 名称.

        Returns:
            TagCommunication: plc 标签实例.
        """
        return getattr(self, f"plc_{plc_name}")

    def write_operation(self, call_back: dict = None, plc_instance: TagCommunication = None):
        """向 plc 地址位写入数据.

        Args:
            call_back (dict): 要写入值的地址位信息.
            plc_instance: plc_instance.
        """
        tag_name, data_type = call_back.get("tag_name"), call_back.get("data_type")
        write_value = call_back.get("value")
        if "sv" in str(write_value):
            sv_name = write_value.split(":")[-1]
            write_value = self.get_sv_value_with_name(sv_name)

        if premise_tag_name := call_back.get("premise_tag_name"):
            self.write_with_condition(
                tag_name, premise_tag_name, call_back.get("premise_value"), data_type, write_value,
                time_out=call_back.get("premise_time_out", 5), plc_instance=plc_instance
            )
        else:
            self.write_no_condition(tag_name, write_value, data_type, plc_instance=plc_instance)

    @staticmethod
    def write_no_condition(tag_name: str, write_value: Union[int, str, bool], data_type: str, plc_instance: TagCommunication = None):
        """根据 tag_name 写入指定类型的值.

        Args:
            tag_name (str): 标签名称.
            write_value (Union[int, str, bool]): 要写入的值.
            data_type (str): 要写入值的类型.
            plc_instance (str): plc名称.
        """
        plc_instance.execute_write(tag_name, data_type, write_value)

    def write_with_condition(
            self, tag_name, premise_tag_name, premise_value, data_type, write_value, time_out=360000, plc_instance: TagCommunication = None
    ):
        """Write value with condition.

        Args:
            tag_name (str): 要清空信号的地址位置.
            premise_tag_name (str): 根据这地址位的值来清空信号.
            premise_value (bool): 清空地址的判断值.
            data_type (str): 要写入数据类型.
            write_value (str, int): 要写入的数据.
            time_out (int): 超时时间.
            plc_instance (str): plc名称.
        """
        expect_time = time_out
        self.logger.info(f"*** Start get premise condition value *** -> tag_name: {premise_tag_name}")
        real_premise_value = plc_instance.execute_read(premise_tag_name, TagTypeEnum.BOOL.value)
        self.logger.info(f"*** End get premise condition value *** -> real_value: {real_premise_value}, "
                         f"expect_value: {premise_value}")
        if premise_value == real_premise_value:
            plc_instance.execute_write(tag_name, data_type, write_value)
            return

        while time_out:
            self.logger.info(f"*** Start get premise condition value *** -> tag_name: {premise_tag_name}")
            real_premise_value = plc_instance.execute_read(premise_tag_name, "bool")
            self.logger.info(
                f"*** End get premise condition value *** -> real_value: {real_premise_value}, "
                f"expect_value: {premise_value}"
            )
            if premise_value == real_premise_value:
                break
            time.sleep(1)
            time_out -= 1
            if time_out == 0:
                self.logger.error(f"*** plc 超时 *** -> plc 未在 {expect_time}s 内及时回复! clear mes signal")
        plc_instance.execute_write(tag_name, "bool", write_value)

    def get_real_sv_name(self, sv_name: str, plc_instance: TagCommunication):
        """根据输入的sv_name 获取真正的sv_name.

        Args:
            sv_name (str): 输入的sv_name.
            plc_instance: plc_instance.
        """
        plc_name = self.get_plc_name(plc_instance)
        if "pp_select" in sv_name or sv_name in ("track_in_product_sn", "product_type"):
            return sv_name
        return f"{sv_name}_{plc_name}"

    def get_real_event_name(self, event_name: str):
        """根据输入的 event_name 获取真正的 event_name.

        Args:
            event_name (str): 输入的sv_name.
        """
        current_thread_name = self.get_current_thread_name()
        if "track_in" in current_thread_name:
            return event_name
        return f"{event_name}_{current_thread_name.split('_')[-1]}"

    def read_operation_update_sv(self, call_back: dict = None, plc_instance: TagCommunication = None):
        """读取 plc 数据, 更新sv.

        Args:
            call_back (dict): 读取地址位的信息.
            plc_instance: plc_name.
        """
        tag_name, data_type = call_back.get("tag_name"), call_back.get("data_type")
        if premise_tag_name := call_back.get("premise_tag_name"):
            plc_value = self.read_with_condition(
                tag_name, premise_tag_name, call_back.get("premise_value"), data_type, plc_instance=plc_instance,
                time_out=call_back.get("premise_time_out")
            )
            self.set_sv_value_with_name(self.get_real_sv_name(call_back.get("sv_name"), plc_instance), plc_value)
            return
        if isinstance(tag_name, dict):
            track_out_pins_state_name = self.get_real_sv_name("pins_state", plc_instance)
            self.set_sv_value_with_name(track_out_pins_state_name, [])
            tag_count, pre_tag_name = list(tag_name.items())[0]
            for index in range(int(tag_count)):
                plc_value = plc_instance.execute_read(f"{pre_tag_name}[{index}]", data_type)
                self.status_variables.get(self.get_sv_id_with_name(track_out_pins_state_name)).value.append(plc_value)
        elif isinstance(tag_name, str):
            plc_value = plc_instance.execute_read(tag_name, data_type)
            self.set_sv_value_with_name(self.get_real_sv_name(call_back.get("sv_name"), plc_instance), plc_value)

    def read_with_condition(
            self, tag_name, premise_tag_name, premise_value, data_type, time_out=36000, plc_instance: TagCommunication = None
    ) -> Union[str, int, bool]:
        """根据条件信号读取指定标签的值.

        Args:
            tag_name (str): 要读取值的标签.
            premise_tag_name (str): 根据这地址位的值来读取数据.
            premise_value (bool): 条件标签的值.
            data_type (str): 要读取数据类型.
            time_out (int): 超时时间.
            plc_instance: plc_instance.
        Returns:
            Union[str, int, bool]: 返回读取标签的值.
        """
        expect_time = time_out
        self.logger.info(f"*** Start get premise condition value *** -> tag_name: {premise_tag_name}")
        real_premise_value = plc_instance.execute_read(premise_tag_name, TagTypeEnum.BOOL.value)
        self.logger.info(f"*** End get premise condition value *** -> real_value: {real_premise_value}, "
                         f"expect_value: {premise_value}")
        if premise_value == real_premise_value:
            return plc_instance.execute_read(tag_name, data_type)
        while time_out:
            time.sleep(1)
            self.logger.info(f"*** Start get premise condition value *** -> tag_name: {premise_tag_name}")
            real_premise_value = plc_instance.execute_read(premise_tag_name, "bool")
            self.logger.info(
                f"*** End get premise condition value *** -> real_value: {real_premise_value}, "
                f"expect_value: {premise_value}"
            )
            if premise_value == real_premise_value:
                break
            time_out -= 1
            if time_out == 0:
                self.logger.error(f"*** plc 超时 *** -> plc 未在 {expect_time}s 内及时回复!")
        return plc_instance.execute_read(tag_name, data_type)

    def get_callback(self, signal_name: str) -> list:
        """根据 signal_name 获取对应的 callback.

        Args:
            signal_name: 信号名称.

        Returns:
            list: 要执行的操作列表.
        """
        return self.get_config_value("plc_signal_tag_name")[signal_name].get("call_back")

    def set_clear_alarm(self, alarm_code: int, plc_instance: TagCommunication):
        """通过S5F1发送报警和解除报警.

        Args:
            alarm_code (int): 报警code, 2: 报警, 9: 清除报警.
            plc_instance: plc_instance.
        """
        if alarm_code == 2:
            alarm_id_str = plc_instance.execute_read(self.get_tag_name("alarm_id"), TagTypeEnum.STRING.value)
            if alarm_instance := self.alarms.get(alarm_id_str):
                self.alarm_id = I4(int(alarm_id_str))
                self.alarm_text = f"{self.get_plc_name(plc_instance)}:{alarm_instance.text}"
            else:
                self.alarm_id = I4(int(alarm_id_str))
                self.alarm_text = "alarm text is not define."

        def _alarm_sender(_alarm_code):
            self.send_and_waitfor_response(
                self.stream_function(5, 1)({
                    "ALCD": _alarm_code, "ALID": self.alarm_id, "ALTX": self.alarm_text
                })
            )
        threading.Thread(target=_alarm_sender, args=(alarm_code,), daemon=True).start()

    @staticmethod
    def get_plc_name(plc_instance: TagCommunication) -> str:
        """获取当前plc名称.

        Returns:
            str: 返回当前plc名称.
        """
        plc_ip_map_name = {
            "10.21.142.10": "in",
            "10.21.142.30": "st1020",
            "10.21.142.70": "st1021",
            "10.21.142.110": "st1022"
        }
        return plc_ip_map_name[plc_instance.ip]

    def save_current_recipe_local(self, plc_name: str):
        """保存当前的配方id和name.

        Args:
            plc_name: plc_name.
        """
        self.config[f"current_recipe_id_name_{plc_name}"] = self.get_sv_value_with_name(f"current_recipe_id_name_{plc_name}")
        self.update_config(f"{'/'.join(self.__module__.split('.'))}.conf", self.config)

    def on_sv_value_request(self, sv_id: Base, status_variable: StatusVariable) -> Base:
        """Get the status variable value depending on its configuration.

        Args:
            sv_id (Base): The id of the status variable encoded in the corresponding type.
            status_variable (StatusVariable): The status variable requested.

        Returns:
            The value encoded in the corresponding type
        """
        del sv_id
        # noinspection PyTypeChecker
        if issubclass(status_variable.value_type, Array):
            return status_variable.value_type(U4, status_variable.value)
        return status_variable.value_type(status_variable.value)

    def _on_s07f19(self, handler, packet):
        """Host查看设备的所有配方."""
        del handler
        return self.stream_function(7, 20)(list(self.get_config_value("recipes", {}).keys()))

    def _on_s10f03(self, handler, packet):
        """Host发送弹框信息显示."""
        del handler
        parser_result = self.get_receive_data(packet)
        terminal_id = parser_result.get("TID")
        terminal_text = parser_result.get("TEXT")
        self.logger.info(f"*** 显示内容 *** -> %s: %s", terminal_id, terminal_text)
        return self.stream_function(10, 4)(ACKC10.ACCEPTED)

    def _on_rcmd_pp_select(self, recipe_id_name: str, station_id: int):
        """Host发送s02f41配方切换.

        Args:
            recipe_id_name (str): 要切换的配方id_name.
            station_id (int): 切换配方的工位.
        """
        station_map = {1: "st1020", 2: "st1021", 3: "st1022", 0: "in"}
        plc_name = station_map[int(station_id)]

        recipe_id, recipe_name, _, *args = recipe_id_name.split("_")
        self.set_sv_value_with_name("pp_select_recipe_id", int(recipe_id))
        self.set_sv_value_with_name("pp_select_recipe_name", recipe_name)

        # 根据配置文件下的call_back执行具体的操作
        self.execute_call_backs(self.get_callback("pp_select"), self.get_plc_instance(plc_name))

        # 切换成功, 更新当前配方id_name, 保存当前配方
        pp_select_success_state = self.get_config_value("pp_select_success_state")
        if self.get_sv_value_with_name("pp_select_state") == pp_select_success_state:
            self.set_sv_value_with_name("pp_select_recipe_id_name", recipe_id_name)
            self.set_sv_value_with_name(f"current_recipe_id_name_{plc_name}", recipe_id_name)
            self.save_current_recipe_local(plc_name)

        self.send_s6f11(f"pp_select_{plc_name}")  # 触发 pp_select 事件

    def _on_rcmd_track_in_reply(self, product_type: str, product_sn: str):
        """Host发送s02f41产品进站回复.

        Args:
            product_type (str): 产品流线.
            product_sn (str): 进站产品码.
        """
        self.logger.info("*** EAP 回复的产品码 *** -> %s", product_sn)

        self.set_sv_value_with_name("product_type", int(product_type))

        self.set_sv_value_with_name("track_in_reply_flag", True)
        self.logger.info("*** eap回复了进站请求 ***")
