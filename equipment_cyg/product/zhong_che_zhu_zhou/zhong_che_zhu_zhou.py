# pylint: skip-file
"""中车株洲拨针设备."""
import json
import threading
import time
from typing import Union
from secsgem.gem import StatusVariable
from secsgem.secs.data_items import ACKC7, ACKC10
from secsgem.secs.variables import I4, Base, Array, U4
from equipment_cyg.controller.controller import Controller
from equipment_cyg.utils.plc.exception import PLCWriteError, PLCReadError, PLCRuntimeError
from equipment_cyg.utils.plc.tag_communication import TagCommunication
from equipment_cyg.utils.plc.tag_type_enum import TagTypeEnum


# pylint: disable=W1203
# noinspection DuplicatedCode
class ZhongCheZhuZhou(Controller):  # pylint: disable=R0901
    """中车株洲class."""
    def __init__(self):
        super().__init__()
        self.recipes = self.get_config_value("recipes", {})  # 获取所有上传过的配方信息
        self.alarm_id = I4(0)  # 保存报警id
        self.alarm_text = ""  # 保存报警内容

        self.set_plc_current_recipe("in")  # 断电重启, 设备plc上次执行的配方
        self.set_plc_current_recipe("st1020")  # 断电重启, 设备plc上次执行的配方
        self.set_plc_current_recipe("st1021")  # 断电重启, 设备plc上次执行的配方
        self.set_plc_current_recipe("st1022")  # 断电重启, 设备plc上次执行的配方

        self.plc_in = TagCommunication(self.get_inovance_dll_path(), self.get_config_value("plc_ip_in"))
        self.plc_in.logger.addHandler(self.file_handler)  # 保存plc日志到文件

        self.plc_st1020 = TagCommunication(self.get_inovance_dll_path(), self.get_config_value("plc_ip_st1020"))
        self.plc_st1020.logger.addHandler(self.file_handler)  # 保存plc日志到文件

        self.plc_st1021 = TagCommunication(self.get_inovance_dll_path(), self.get_config_value("plc_ip_st1021"))
        self.plc_st1021.logger.addHandler(self.file_handler)  # 保存plc日志到文件

        self.plc_st1022 = TagCommunication(self.get_inovance_dll_path(), self.get_config_value("plc_ip_st1022"))
        self.plc_st1022.logger.addHandler(self.file_handler)  # 保存plc日志到文件

        self.enable_equipment()  # 启动MES服务

        self.start_monitor_plc_thread()  # 启动监控plc信号线程

    def set_plc_current_recipe(self, plc_name: str):
        """设置plc上次执行的配方.

        Args:
            plc_name (str): plc 名称.
        """
        self.set_sv_value_with_name(
            f"current_recipe_id_name_{plc_name}",
            self.get_config_value(f"current_recipe_id_name_{plc_name}", "")
        )

    def connect_plc(self, plc_instance: TagCommunication):
        """连接plc.

        Args:
            plc_instance (TagCommunication): plc 标签通讯实例.
        """
        if plc_instance.communication_open():
            self.logger.warning(f"*** First connect to plc success *** -> plc地址是: {self.plc_in.ip}.")
        else:
            self.logger.warning(f"*** First connect to plc failure *** -> plc地址是: {self.plc_in.ip}.")

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
                    current_control_state_name = self.get_real_sv_or_event_name("current_control_state")
                    if control_state != self.get_sv_value_with_name(current_control_state_name):
                        self.set_sv_value_with_name(current_control_state_name, control_state)
                        self.send_s6f11(self.get_real_sv_or_event_name("control_state_change"))
                except PLCReadError as e:
                    self.logger.warning(f"*** Read failure: control_state *** -> reason: {str(e)}!")
                    time.sleep(self.get_config_value("wait_time_plc_disconnect"))
        threading.Thread(
            target=_control_state, daemon=True, args=(plc_instance, plc_name,),
            name=f"control_state_thread_{plc_name}"
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
                    current_machine_state_name = self.get_real_sv_or_event_name("current_machine_state")
                    if machine_state != self.get_sv_value_with_name(current_machine_state_name):
                        alarm_state = self.get_config_value("alarm_state")
                        if machine_state == alarm_state:
                            self.set_clear_alarm(2)
                        elif self.get_sv_value_with_name(current_machine_state_name) == alarm_state:
                            self.set_clear_alarm(self.get_config_value("reset_alarm_code"))
                        self.set_sv_value_with_name(current_machine_state_name, machine_state)
                        self.send_s6f11(self.get_real_sv_or_event_name("machine_state_change"))
                except PLCReadError as e:
                    self.logger.warning(f"*** Read failure: machine_state *** -> reason: {str(e)}!")
                    time.sleep(self.get_config_value("wait_time_plc_disconnect"))
        threading.Thread(
            target=_machine_state, daemon=True, args=(plc_instance, plc_name),
            name=f"machine_state_thread_{plc_name}"
        ).start()

    def bool_signal_thread(self, plc_name: str):
        """bool 类型信号的线程."""
        plc_instance = self.get_plc_instance(plc_name)

        def _bool_signal(_plc_instance, _plc_name, **kwargs):
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
                # pylint: disable=W0106
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
                         f"地址位: {signal_info.get('tag_name')} {'=' * 40}")

        self.execute_call_backs(call_back_list)  # 根据配置文件下的call_back执行具体的操作

        self.logger.info(f"{'=' * 40} Signal clear: {signal_info.get('description')} {'=' * 40}")

    def wait_eap_reply(self, call_back=None, time_out=5):
        """等待EAP回复进站."""
        while not self.get_sv_value_with_name("track_in_reply_flag"):
            time_out -= 1
            time.sleep(1)
            if time_out == 0:
                self.logger.warning("*** EAP 回复超时 *** -> EAP 未在5秒内回复进站.")

    @Controller.try_except_exception(PLCRuntimeError("*** Execute call backs error ***"))
    def execute_call_backs(self, call_backs: list, time_out=5):
        """根据操作列表执行具体的操作.

        Args:
            call_backs (list): 要执行动作的信息列表, 按照列表顺序执行.
            time_out (int): 超时时间.

        Raises:
            PLCRuntimeError: 在执行配置文件下的步骤时出现异常.
        """
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
            operation_func(call_back=call_back, time_out=time_out)
            self.is_send_event(call_back)
            self.logger.info(f"{'-' * 30} 结束 Success: {call_back.get('description')} {'-' * 30}")

    def is_send_event(self, call_back):
        """判断是否要发送事件."""
        if (event_name := call_back.get("event_name")) in self.get_config_value("collection_events"):  # 触发事件
            self.send_s6f11(event_name)

    def get_plc_instance(self, plc_name: str) -> TagCommunication:
        """根据plc名称获取plc标签实例.

        Args:
            plc_name (str): plc 名称.

        Returns:
            TagCommunication: plc 标签实例.
        """
        return getattr(self, f"plc_{plc_name}")

    def write_operation(self, call_back: dict = None, time_out=5):
        """向 plc 地址位写入数据.

        Args:
            call_back (dict): 要写入值的地址位信息.
            time_out: 设置超时时间, 默认 5s 超时.
        """
        tag_name, data_type = call_back.get("tag_name"), call_back.get("data_type")
        write_value = call_back.get("value")
        if "sv" in str(write_value):
            sv_name = write_value.split(":")[-1]
            write_value = self.get_sv_value_with_name(sv_name)

        if premise_tag_name := call_back.get("premise_tag_name"):
            self.write_with_condition(
                tag_name, premise_tag_name, call_back.get("premise_value"), data_type, write_value, time_out=time_out
            )
        else:
            self.write_no_condition(tag_name, write_value, data_type)

    def write_no_condition(self, tag_name: str, write_value: Union[int, str, bool], data_type: str):
        """根据 tag_name 写入指定类型的值.

        Args:
            tag_name (str): 标签名称.
            write_value (Union[int, str, bool]): 要写入的值.
            data_type (str): 要写入值的类型.
        """
        self.plc_in.execute_write(tag_name, data_type, write_value)

    def write_with_condition(
            self, tag_name, premise_tag_name, premise_value, data_type, write_value, time_out=5
    ):
        """Write value with condition.

        Args:
            tag_name (str): 要清空信号的地址位置.
            premise_tag_name (str): 根据这地址位的值来清空信号.
            premise_value (bool): 清空地址的判断值.
            data_type (str): 要写入数据类型.
            write_value (str, int): 要写入的数据.
            time_out (int): 超时时间.
        """
        expect_time = time_out
        self.logger.info(f"*** Start get premise condition value *** -> tag_name: {premise_tag_name}")
        real_premise_value = self.plc_in.execute_read(premise_tag_name, TagTypeEnum.BOOL.value)
        self.logger.info(f"*** End get premise condition value *** -> real_value: {real_premise_value}, "
                         f"expect_value: {premise_value}")
        if premise_value == real_premise_value:
            self.plc_in.execute_write(tag_name, data_type, write_value)
        else:
            while time_out:
                self.logger.info(f"*** Start get premise condition value *** -> tag_name: {premise_tag_name}")
                real_premise_value = self.plc_in.execute_read(premise_tag_name, "bool")
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
            self.plc_in.execute_write(tag_name, "bool", write_value)

    def get_real_sv_or_event_name(self, sv_or_event_name_input: str):
        """根据输入的sv_name or event_name获取真正的sv_name or event_name.

        Args:
            sv_or_event_name_input (str): 输入的sv_name or event_name.
        """
        return f"{sv_or_event_name_input}_{self.get_current_thread_name().split('_')[-1]}"

    def read_operation_update_sv(self, call_back: dict = None, time_out=5):
        """读取 plc 数据, 更新sv.

        Args:
            call_back (dict): 读取地址位的信息.
            time_out: 设置超时时间, 默认 5s 超时.
        """
        tag_name, data_type = call_back.get("tag_name"), call_back.get("data_type")
        if premise_tag_name := call_back.get("premise_tag_name"):
            plc_value = self.read_with_condition(
                tag_name, premise_tag_name, call_back.get("premise_value"), data_type, time_out=time_out
            )
            self.set_sv_value_with_name(self.get_real_sv_or_event_name(call_back.get("sv_name")), plc_value)
        else:
            if isinstance(tag_name, dict):
                tag_count, pre_tag_name = list(tag_name.items())[0]
                for index in range(1, tag_count + 1):
                    plc_value = self.plc_in.execute_read(f"{pre_tag_name}[{index}]", data_type)
                    track_out_pins_state_name = self.get_real_sv_or_event_name("track_out_pins_state")
                    self.status_variables.get(self.get_sv_id_with_name(track_out_pins_state_name)).value.append(
                        plc_value
                    )
            elif isinstance(tag_name, str):
                plc_value = self.plc_in.execute_read(tag_name, data_type)
                self.set_sv_value_with_name(self.get_real_sv_or_event_name(call_back.get("sv_name")), plc_value)

    def read_with_condition(
            self, tag_name, premise_tag_name, premise_value, data_type, time_out=5
    ) -> Union[str, int, bool]:
        """根据条件信号读取指定标签的值.

        Args:
            tag_name (str): 要读取值的标签.
            premise_tag_name (str): 根据这地址位的值来读取数据.
            premise_value (bool): 条件标签的值.
            data_type (str): 要读取数据类型.
            time_out (int): 超时时间.

        Returns:
            Union[str, int, bool]: 返回读取标签的值.
        """
        expect_time = time_out
        self.logger.info(f"*** Start get premise condition value *** -> tag_name: {premise_tag_name}")
        real_premise_value = self.plc_in.execute_read(premise_tag_name, TagTypeEnum.BOOL.value)
        self.logger.info(f"*** End get premise condition value *** -> real_value: {real_premise_value}, "
                         f"expect_value: {premise_value}")
        if premise_value == real_premise_value:
            return self.plc_in.execute_read(tag_name, data_type)
        while time_out:
            time.sleep(1)
            self.logger.info(f"*** Start get premise condition value *** -> tag_name: {premise_tag_name}")
            real_premise_value = self.plc_in.execute_read(premise_tag_name, "bool")
            self.logger.info(
                f"*** End get premise condition value *** -> real_value: {real_premise_value}, "
                f"expect_value: {premise_value}"
            )
            if premise_value == real_premise_value:
                break
            time_out -= 1
            if time_out == 0:
                self.logger.error(f"*** plc 超时 *** -> plc 未在 {expect_time}s 内及时回复!")
        return self.plc_in.execute_read(tag_name, data_type)

    def get_tag_name(self, name):
        """根据传入的 name 获取 plc 定义的标签.

        Args:
            name (str): 配置文件里给 plc 标签自定义的变量名.

        Returns:
            str: 返回 plc 定义的标签
        """
        return self.config["plc_signal_tag_name"][name]["tag_name"]

    def save_current_recipe(self):
        """保存plc上传的配方id和name."""
        self.config["current_recipe_id_name"] = self.get_sv_value_with_name("current_recipe_id_name")
        self.update_config(f"{'/'.join(self.__module__.split('.'))}.conf", self.config)

    def get_callback(self, signal_name: str) -> list:
        """根据 signal_name 获取对应的 callback.

        Args:
            signal_name: 信号名称.

        Returns:
            list: 要执行的操作列表.
        """
        return self.get_config_value("plc_signal_tag_name")[signal_name].get("call_back")

    def set_clear_alarm(self, alarm_code: int):
        """通过S5F1发送报警和解除报警.

        Args:
            alarm_code (int): 报警code, 2: 报警, 9: 清除报警.
        """
        if alarm_code == 2:
            alarm_id_str = self.plc_in.execute_read(self.get_tag_name("alarm_id"), TagTypeEnum.STRING.value)
            self.alarm_id = I4(int(alarm_id_str))
            self.alarm_text = f"{self.get_plc_name()}:{self.alarms.get(alarm_id_str).text}"

        def _alarm_sender(_alarm_code):
            self.send_and_waitfor_response(
                self.stream_function(5, 1)({
                    "ALCD": _alarm_code, "ALID": self.alarm_id, "ALTX": f"{self.get_plc_name()}:{self.alarm_text}"
                })
            )
        threading.Thread(target=_alarm_sender, args=(alarm_code,), daemon=True).start()

    def get_plc_name(self) -> str:
        """获取当前plc名称.

        Returns:
            str: 返回当前plc名称.
        """
        return self.get_current_thread_name().split("_")[-1]

    # noinspection PyUnusedLocal
    def save_recipe(self, call_back=None, **kwargs) -> None:
        """保存plc上传的配方信息.

        Args:
            call_back (dict): 配方信息的字典.
        """
        recipe_info_tags = call_back.get("recipe_info_tags")
        recipe_id = self.get_sv_value_with_name(self.get_real_sv_or_event_name("upload_recipe_id"))
        recipe_name = self.get_sv_value_with_name(self.get_real_sv_or_event_name("upload_recipe_name"))
        recipe_id_name = f"{recipe_id}_{recipe_name}_{self.get_plc_name()}"
        self.recipes[recipe_id_name] = {}

        def _save_recipe_thread(_recipe_id_name, _recipe_info_tags):
            for key_data_type, tag_name in _recipe_info_tags.items():
                key, data_type = key_data_type.split(",")
                if "_" in data_type:
                    value_num, data_type = data_type.split("_")
                    for index in range(int(value_num)):
                        plc_value = self.plc_in.execute_read(f"{tag_name}[{index}]", data_type)
                        self.recipes[_recipe_id_name].update({f"{key}{index}": plc_value})
                else:
                    plc_value = self.plc_in.execute_read(tag_name, data_type)
                    self.recipes[_recipe_id_name].update({key: plc_value})
            self.save_recipes_local()  # 保存所有的配方信息在本地

        threading.Thread(target=_save_recipe_thread, args=(recipe_id_name, recipe_info_tags,), daemon=True).start()

    def save_recipes_local(self):
        """保存plc上传的配方id和name."""
        self.config["recipes"] = self.recipes
        self.update_config(f"{'/'.join(self.__module__.split('.'))}.conf", self.config)

    def save_current_recipe_local(self):
        """保存当前的配方id和name."""
        self.config["current_recipe_id_name"] = self.get_sv_value_with_name("current_recipe_id_name")
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

    def _on_s07f03(self, handler, packet):
        """Host给PC下发配方, 保存EAP下发的配方, 针对这个设备不做任何操作."""
        del handler
        return self.stream_function(7, 4)(ACKC7.ACCEPTED)

    def _on_s07f05(self, handler, packet):
        """Host请求上传配方内容."""
        del handler
        parser_result = self.get_receive_data(packet)
        recipe_name = parser_result
        pp_body = json.dumps(self.recipes[recipe_name])
        return self.stream_function(7, 6)([recipe_name, pp_body])

    def _on_s07f19(self, handler, packet):
        """Host查看设备的所有配方."""
        del handler
        return self.stream_function(7, 20)(list(self.recipes.keys()))

    def _on_s10f03(self, handler, packet):
        """Host发送弹框信息显示."""
        del handler
        parser_result = self.get_receive_data(packet)
        terminal_id = parser_result.get("TID")
        terminal_text = parser_result.get("TEXT")
        return self.stream_function(10, 4)(ACKC10.ACCEPTED)

    def _on_rcmd_pp_select(self, recipe_id_name):
        """Host发送s02f41配方切换, 切换配方前先询问, 然后在切换.

        Args:
            recipe_id_name (str): 要切换的配方id_name.
        """
        recipe_id, recipe_name, *args = recipe_id_name.split("_")
        self.set_sv_value_with_name(self.get_real_sv_or_event_name("pp_select_recipe_id"), int(recipe_id))
        self.set_sv_value_with_name(self.get_real_sv_or_event_name("pp_select_recipe_name"), recipe_name)
        # noinspection PyBroadException
        try:  # 根据配置文件下的call_back执行具体的操作
            self.execute_call_backs(self.get_callback("pp_select"))
        except PLCRuntimeError:
            pass
        except Exception:
            pass

        # 切换成功, 更新当前配方id_name, 保存当前配方
        pp_select_success_state = self.get_config_value("pp_select_success_state")
        if self.get_sv_value_with_name(self.get_real_sv_or_event_name("pp_select_state")) == pp_select_success_state:
            self.set_sv_value_with_name(self.get_real_sv_or_event_name("pp_select_recipe_id_name"), recipe_id_name)
            self.set_sv_value_with_name(self.get_real_sv_or_event_name("current_recipe_id_name"), recipe_id_name)
            self.save_current_recipe_local()

        self.send_s6f11(self.get_real_sv_or_event_name("pp_select"))  # 触发 pp_select 事件

    def _on_rcmd_track_in_reply(self, product_type: str, product_sn: str, state: int):
        """Host发送s02f41产品进站回复.

        Args:
            product_type (str): 产品流线.
            product_sn (str): 进站产品码.
            state (int): 进站产品状态.
        """
        product_type_map = {"A": 1, "B": 2, "C": 3}
        try:
            self.set_sv_value_with_name("product_type", product_type_map.get(product_type))
        except KeyError:
            self.set_sv_value_with_name("product_type", 9)

        self.set_sv_value_with_name("track_in_reply_flag", True)
