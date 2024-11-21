"""中心扫码设备."""
import copy
import json
import re
import threading
import time
from typing import Union

from inovance_tag.exception import PLCReadError, PLCRuntimeError, PLCWriteError
from inovance_tag.tag_communication import TagCommunication
from inovance_tag.tag_type_enum import TagTypeEnum
from secsgem.secs.data_items import ACKC7, ACKC10
from secsgem.secs.variables import I4

from equipment_cyg.controller.controller import Controller


# noinspection DuplicatedCode
class ZhongXinScan(Controller):  # pylint: disable=R0901
    """中心扫码设备 class."""

    def __init__(self):
        super().__init__()
        self.recipes = self.get_config_value("recipes", {})  # 获取所有上传过的配方信息
        self.alarm_id = I4(0)  # 保存报警id
        self.alarm_text = ""  # 保存报警内容
        self.set_sv_value_with_name("current_recipe_id_name", self.get_config_value("current_recipe_id_name", ""))
        self.plc = TagCommunication(self.get_config_value("plc_ip"))
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
            tag_name = self.get_tag_name("mes_heart")
            while True:
                try:
                    self.plc.execute_write(tag_name, TagTypeEnum.BOOL.value, True, save_log=False)
                    time.sleep(self.get_config_value("mes_heart_time"))
                    self.plc.execute_write(tag_name, TagTypeEnum.BOOL.value, False, save_log=False)
                    time.sleep(self.get_config_value("mes_heart_time"))
                except PLCWriteError as e:
                    self.set_sv_value_with_name("current_control_state", 0)

                    self.logger.warning(f"*** Write failure: mes_heart *** -> reason: {str(e)}!")
                    if self.plc.communication_open() is False:
                        wait_time = self.get_config_value("wait_time_plc_disconnect")
                        self.logger.warning(f"*** Plc connect attempt *** -> wait {wait_time}s attempt connect again.")
                        time.sleep(wait_time)
                    else:
                        self.logger.warning(f"*** After exception plc connect success *** -> plc地址是: {self.plc.ip}.")

        threading.Thread(target=_mes_heart, daemon=True, name="mes_heart_thread").start()

    def control_state_thread(self):
        """控制状态变化的线程."""

        def _control_state():
            """监控控制状态变化."""
            tag_name = self.get_tag_name("control_state")
            data_type = self.get_tag_data_type("control_state")
            while True:
                try:
                    control_state = 2 if self.plc.execute_read(tag_name, data_type, save_log=False) else 1
                    if control_state != self.get_sv_value_with_name("current_control_state"):
                        self.set_sv_value_with_name("current_control_state", control_state)
                        self.send_s6f11("control_state_change")
                except PLCReadError as e:
                    self.logger.warning(f"*** Read failure: control_state *** -> reason: {str(e)}!")
                    time.sleep(self.get_config_value("wait_time_plc_disconnect"))

        threading.Thread(target=_control_state, daemon=True, name="control_state_thread").start()

    def machine_state_thread(self):
        """运行状态变化的线程."""

        def _machine_state():
            """监控运行状态变化."""
            tag_name = self.get_tag_name("machine_state")
            while True:
                try:
                    machine_state = self.plc.execute_read(tag_name, TagTypeEnum.INT.value, save_log=False)
                    if machine_state != self.get_sv_value_with_name("current_machine_state"):
                        alarm_state = self.get_config_value("alarm_state")
                        if machine_state == alarm_state:
                            self.set_clear_alarm(2)
                        elif self.get_sv_value_with_name("current_machine_state") == alarm_state:
                            self.set_clear_alarm(self.get_config_value("reset_alarm_code"))
                        self.set_sv_value_with_name("current_machine_state", machine_state)
                        self.send_s6f11("machine_state_change")
                except PLCReadError as e:
                    self.logger.warning(f"*** Read failure: machine_state *** -> reason: {str(e)}!")
                    time.sleep(self.get_config_value("wait_time_plc_disconnect"))

        threading.Thread(target=_machine_state, daemon=True, name="machine_state_thread").start()

    def bool_signal_thread(self):
        """bool 类型信号的线程."""

        def _bool_signal(**kwargs):
            """监控 plc bool 信号."""
            self.monitor_plc_address(**kwargs)  # 实时监控plc信号

        plc_signal_dict = self.get_config_value("plc_signal_tag_name", {})
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
                current_value = self.plc.execute_read(kwargs.get("tag_name"), TagTypeEnum.BOOL.value, False)
                # pylint: disable=W0106
                if self.get_sv_value_with_name("current_control_state") in (0, 1):
                    continue
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

    def write_operation(self, call_back: dict, time_out=180):
        """向 plc 地址位写入数据.

        Args:
            call_back (dict): 要写入值的地址位信息.
            time_out: 设置超时时间, 默认 180s 超时.
        """
        tag_name, data_type = call_back.get("tag_name"), call_back.get("data_type")
        write_value = call_back.get("value")
        if "sv" in str(write_value):
            sv_name = write_value.split(":")[-1]
            write_value = self.get_sv_value_with_name(sv_name)
        if "dv" in str(write_value):
            dv_name = write_value.split(":")[-1]
            write_value = self.get_dv_value_with_name(dv_name)

        if premise_tag_name := call_back.get("premise_tag_name"):
            self.write_with_condition(
                tag_name, premise_tag_name, call_back.get("premise_value"),
                data_type, write_value, time_out=time_out, premise_data_type=call_back.get("premise_data_type")
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
        self.plc.execute_write(tag_name, data_type, write_value)

    def write_with_condition(
            self, tag_name, premise_tag_name, premise_value, data_type, write_value, time_out=180,
            premise_data_type="bool"
    ):
        """Write value with condition.

        Args:
            tag_name (str): 要清空信号的地址位置.
            premise_tag_name (str): 根据这地址位的值来清空信号.
            premise_value (bool): 清空地址的判断值.
            data_type (str): 要写入数据类型.
            write_value (str, int): 要写入的数据.
            time_out (int): 超时时间.
            premise_data_type (str): 前提条件标签的类型, 默认是bool.
        """
        expect_time = time_out
        self.logger.info(f"*** Start get premise condition value *** -> tag_name: {premise_tag_name}")
        real_premise_value = self.plc.execute_read(premise_tag_name, premise_data_type)
        self.logger.info(f"*** End get premise condition value *** -> real_value: {real_premise_value}, "
                         f"expect_value: {premise_value}")
        if bool(premise_value) == bool(real_premise_value):
            self.plc.execute_write(tag_name, data_type, write_value)
        else:
            while time_out:
                self.logger.info(f"*** Start get premise condition value *** -> tag_name: {premise_tag_name}")
                real_premise_value = self.plc.execute_read(premise_tag_name, premise_data_type)
                self.logger.info(
                    f"*** End get premise condition value *** -> real_value: {real_premise_value}, "
                    f"expect_value: {premise_value}"
                )
                if bool(premise_value) == bool(real_premise_value):
                    break
                time.sleep(1)
                time_out -= 1
                if time_out == 0:
                    self.logger.error(f"*** plc 超时 *** -> plc 未在 {expect_time}s 内及时回复! clear mes signal")
            self.plc.execute_write(tag_name, data_type, write_value)

    def read_operation_update_sv(self, call_back: dict, time_out=180):
        """读取 plc 数据, 更新sv.

        Args:
            call_back (dict): 读取地址位的信息.
            time_out: 设置超时时间, 默认 5s 超时.
        """
        tag_name, data_type = call_back.get("tag_name"), call_back.get("data_type")
        if premise_tag_name := call_back.get("premise_tag_name"):
            plc_value = self.read_with_condition(
                tag_name, premise_tag_name, call_back.get("premise_value"), data_type, time_out=time_out,
                premise_data_type=call_back.get("premise_data_type")
            )
            self.set_dv_value_with_name(call_back.get("dv_name"), plc_value)
        else:
            if "ARRAY" in data_type:
                plc_value = []
                tag_num = int(re.findall(r'\$(\d+)', tag_name)[0])
                for i in range(tag_num):
                    _tag_name = re.sub(f"\$\d+", str(i + 1), tag_name)
                    plc_value.append(self.plc.execute_read(_tag_name, data_type.split("-")[-1]))
                if "读取出站产品状态" == call_back.get("description"):
                    current_success_count = self.get_sv_value_with_name("success_count")
                    self.set_sv_value_with_name("success_count",
                                                self.get_product_ok_num(plc_value) + current_success_count)
                    if self.get_sv_value_with_name("success_count") >= self.get_sv_value_with_name("lot_number"):
                        self.send_s6f11("lot_end")
            else:
                plc_value = self.plc.execute_read(tag_name, data_type)
            self.set_dv_value_with_name(call_back.get("dv_name"), plc_value)

    @staticmethod
    def get_product_ok_num(product_states: list):
        """获取OK产品的个数."""
        ok_count = 0
        for state in product_states:
            if state == 1:
                ok_count += 1
        return ok_count

    def read_with_condition(
            self, tag_name, premise_tag_name, premise_value, data_type, time_out=180, premise_data_type="bool"
    ) -> Union[str, int, bool, list]:
        """根据条件信号读取指定标签的值.

        Args:
            tag_name (str): 要读取值的标签.
            premise_tag_name (str): 根据这地址位的值来读取数据.
            premise_value (bool): 条件标签的值.
            data_type (str): 要读取数据类型.
            time_out (int): 超时时间.
            premise_data_type (str): premise_data_type.

        Returns:
            Union[str, int, bool, list]: 返回读取标签的值.
        """
        expect_time = time_out
        self.logger.info(f"*** Start get premise condition value *** -> tag_name: {premise_tag_name}")
        real_premise_value = self.plc.execute_read(premise_tag_name, premise_data_type)
        self.logger.info(f"*** End get premise condition value *** -> real_value: {real_premise_value}, "
                         f"expect_value: {premise_value}")
        if bool(premise_value) == bool(real_premise_value):
            if "ARRAY" in data_type:
                _result = []
                tag_num = int(re.findall(r'\$(\d+)', tag_name)[0])
                for i in range(tag_num):
                    _tag_name = re.sub(f"\$\d+", str(i), tag_name)
                    _result.append(self.plc.execute_read(_tag_name, data_type.split("-")[-1]))
                return _result
            return self.plc.execute_read(tag_name, data_type)
        while time_out:
            time.sleep(1)
            self.logger.info(f"*** Start get premise condition value *** -> tag_name: {premise_tag_name}")
            real_premise_value = self.plc.execute_read(premise_tag_name, premise_data_type)
            self.logger.info(
                f"*** End get premise condition value *** -> real_value: {real_premise_value}, "
                f"expect_value: {premise_value}"
            )
            if bool(premise_value) == bool(real_premise_value):
                break
            time_out -= 1
            if time_out == 0:
                self.logger.error(f"*** plc 超时 *** -> plc 未在 {expect_time}s 内及时回复!")
        return self.plc.execute_read(tag_name, data_type)

    def save_current_recipe_local(self):
        """保存当前的配方id和name."""
        self.config["current_recipe_id_name"] = self.get_sv_value_with_name("current_recipe_id_name")
        self.update_config(f"{'/'.join(self.__module__.split('.'))}.conf", self.config)

    def save_recipes_local(self):
        """保存plc上传的配方id和name."""
        self.config["recipes"] = self.recipes
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
            alarm_id = self.plc.execute_read(self.get_tag_name("alarm_id"), TagTypeEnum.INT.value)
            self.alarm_id = I4(alarm_id)
            self.alarm_text = self.alarms.get(str(alarm_id)).text

        def _alarm_sender(_alarm_code):
            self.send_and_waitfor_response(
                self.stream_function(5, 1)({
                    "ALCD": _alarm_code, "ALID": self.alarm_id, "ALTX": self.alarm_text
                })
            )

        threading.Thread(target=_alarm_sender, args=(alarm_code,), daemon=True).start()

    # noinspection PyUnusedLocal
    def save_recipe(self, **kwargs):
        """保存plc上传的配方信息."""
        recipe_id = self.get_dv_value_with_name("upload_recipe_id")
        recipe_name = self.get_dv_value_with_name("upload_recipe_name")
        recipe_id_name = f"{recipe_id}_{recipe_name}"
        temp_recipes = copy.deepcopy(self.recipes)
        for recipe, recipe_info in temp_recipes.items():
            if str(recipe_id) == recipe.split("_")[0]:
                self.recipes.pop(recipe)
        self.recipes[recipe_id_name] = {}
        self.save_recipes_local()

    def wait_eap_reply(self, call_back=None, time_out=180):
        """等待EAP回复进站."""
        if call_back:
            pass
        while not self.get_dv_value_with_name("track_in_reply_flag"):
            time_out -= 1
            time.sleep(1)
            if time_out == 0:
                self.logger.warning("*** EAP 回复超时 *** -> EAP 未在180秒内回复进站, 告诉设备NG 2")
                self.plc.execute_write(
                    self.get_tag_name("track_in_reply_result"), TagTypeEnum.INT.value,
                    self.get_config_value("track_in_ng_state")
                )

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
        display_str = f"{terminal_id}:{terminal_text}"
        self.plc.execute_write(self.get_tag_name("display_eap_str"), TagTypeEnum.STRING.value, display_str)
        return self.stream_function(10, 4)(ACKC10.ACCEPTED)

    def _on_rcmd_pp_select(self, recipe_id_name):
        """Host发送s02f41配方切换, 切换配方前先询问, 然后在切换.

        Args:
            recipe_id_name (str): 要切换的配方id_name.
        """
        recipe_name_eap = recipe_id_name
        for recipe, recipe_info in self.recipes.items():
            if str(recipe_id_name) in recipe:
                recipe_id_name = recipe
                break
        self.set_dv_value_with_name("pp_select_recipe_id_name", recipe_name_eap)
        recipe_id, recipe_name = recipe_id_name.split("_")
        self.set_dv_value_with_name("pp_select_recipe_id", int(recipe_id))
        self.set_dv_value_with_name("pp_select_recipe_name", recipe_name)
        # noinspection PyBroadException
        try:  # 根据配置文件下的call_back执行具体的操作
            self.execute_call_backs(self.get_callback("pp_select"))
        except PLCRuntimeError:
            pass
        except Exception:  # pylint: disable=W0718
            pass

        # 切换成功, 更新当前配方id_name, 保存当前配方
        if self.get_dv_value_with_name("pp_select_state") == self.get_config_value("pp_select_success_state"):
            self.set_sv_value_with_name("current_recipe_id_name", recipe_name_eap)
            self.save_current_recipe_local()

        self.send_s6f11("pp_select")  # 触发 pp_select 事件

    def _on_rcmd_track_in_reply(self, state):
        """进站回复产品状态, 要不要继续做."""
        self.plc.execute_write(self.get_tag_name("track_in_reply_result"), TagTypeEnum.INT.value, int(state))
        self.set_dv_value_with_name("track_in_reply_flag", True)

    def _on_rcmd_new_lot(self, lot_name, lot_number):
        """开工单, 本次工单要做多少个."""
        self.set_sv_value_with_name("success_count", 0)
        self.set_sv_value_with_name("lot_name", lot_name)
        self.set_sv_value_with_name("lot_number", int(lot_number))

        self.plc.execute_write(self.get_tag_name("new_lot_quality"), "int", int(lot_number))
        self.plc.execute_write(self.get_tag_name("new_lot_signal"), "bool", True)
        while True:
            if self.plc.execute_read(self.get_tag_name("new_lot_plc_reply"), "bool"):
                self.plc.execute_write(self.get_tag_name("new_lot_signal"), "bool", False)
                break
            time.sleep(1)
