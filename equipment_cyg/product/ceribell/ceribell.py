# pylint: skip-file
"""
上传配方:
    1.监控上传配方信号, True
        1. 读取上传的配方名, 将新配方名保存在本地
        2. 通知plc将上传配方名信号清空
        3. 根据上传配方名信号将通知plc信号清空

开工单:
    1.在页面上输入工单, 选择配方后, 点击开工单按钮 lot_id = 输入的工单号, recipe = 选择的配方
    2.先判断 plc can_new_lot_signal 地址位信号, 是 True, 说明可以开新工单
        1. 更新 sv, current_lot_id 的值为 new_lot
        2. 更新 sv, current_recipe 的值为 recipe
        3. 将当前工单、配方和所有plc上传的配方名保存在本地
        4. 写入 plc 将要执行的配方
        5. 通知plc获取新配方
        6. 根据新建工单信号变为False将通知信号清空

plc请求小盒子标识
    1.实时监控plc请求小盒子标识信号
        1.写入小盒子标识
        2.通知 plc 拿小盒子标识
        3.根据 plc 已清除 small_index 信号来清除通知信号

进站:
    1.实时监控进站信号, 是 True
        1.读取左边标签信息, 更新 track_in_label_left
        2.读取右边标签信息, 更新 track_in_label_right
        3.读取左边结果, 更新 track_in_state_left
        4.读取右边结果, 更新 track_in_state_right
        5.读取左边照片
        6.读取右边照片
        7.根据两边结果写入MES反馈结果
        8.通知plc获取MES反馈结果
        9.根据plc进站信号改变为False清空通知信号

透明胶带检查结果事件
    1.实时监控检查气泡信号, 是 True
        1.读取当前气泡检查的盒子索引, check_tape_index
        2.读取照片1结果, 更新 check_state_1
        3.读取照片2结果, 更新 check_state_2
        4.读取照片3结果, 更新 check_state_3
        5.读取照片4结果, 更新 check_state_4
        6.读取照片1
        7.读取照片2
        8.读取照片3
        9.读取照片4
        10.通知plc清除 check_tape_result 信号
        11.根据 plc 已清除 check_tape_result 信号来清除通知信号

打印标签:
    1.实时监控打印标签请求, 是 True
        1.写入打印标签信息
        2.通知plc清除 print_label_request 信号
        3.根据打印标签信号为False清空通知新信号

出站:
    1.实时监控track_out信号, 是 True
        1.读取标签信息, 更新 track_out_label
        2.读取检查结果, 更新 track_out_state
        3.获取包装盒照片
        4.写入MES反馈结果
        5.通知MES检查结果信号, 告诉plc清除 track_out 信号
        6.根据track_out信号变为False清空通知新信号
"""
import asyncio
import json
import os
import threading
import time
from datetime import datetime
from typing import Optional

from equipment_cyg.controller.controller import Controller
from equipment_cyg.utils.airtable.airtable import Airtable
from equipment_cyg.utils.plc.exception import PLCWriteError
from equipment_cyg.utils.plc.tag_communication import TagCommunication
from equipment_cyg.utils.socket.socket_server_asyncio import CygSocketServerAsyncio


# noinspection DuplicatedCode
# pylint: disable=W1203
# pylint: disable=R0904
class Ceribell(Controller):  # pylint: disable=R0901
    """Ceribell 包装机设备类."""
    def __init__(self):
        super().__init__()
        self.upload_dict = {}  # 临时保存上传到airtable的数据

        self.airtable_instance = Airtable(self.get_config_value("airtable_access_token"))
        self.base_id = self.get_config_value("base_id")
        self.sheet_name = self.get_config_value("sheet_name")

        self.recipes = self.get_config_value("current_lot").get("recipes", [])  # 所有的配方名列表
        self.update_current_lot_id(self.get_config_value("current_lot").get("lot_id", ""))
        self.update_current_recipe(self.get_config_value("current_lot").get("current_recipe", ""))

        self.socket_server = CygSocketServerAsyncio(
            self.get_config_value("socket_server_ip", "127.0.0.1"),
            self.get_config_value("socket_server_port", 8000)
        )
        self.socket_server.logger.addHandler(self.file_handler)  # 保存socket日志到文件

        self.plc = TagCommunication(self.get_config_value("dll_path"), self.get_config_value("plc_ip"))
        self.plc.logger.addHandler(self.file_handler)  # 保存plc日志到文件

        self.enable_equipment()  # 启动MES服务

        self.start_socket_server_thread()  # 启动接收web请求的socket服务

        self.start_monitor_plc_thread()  # 启动监控plc信号线程

    # 启动接收web请求的socket服务
    def start_socket_server_thread(self):
        """启动监控 web 页面发来的请求."""
        self.socket_server.operations_return_data = self.operations_return_data

        def _run_socket_server():
            asyncio.run(self.socket_server.run_socket_server())

        thread = threading.Thread(target=_run_socket_server, daemon=True)  # 主程序结束这个线程也结束
        thread.start()

    # 监控 web 页面发来请求进行处理, 然后返回信息
    def operations_return_data(self, byte_data: bytes) -> Optional[str]:
        """监控 web 页面发来请求进行处理, 然后返回信息."""
        request_data = byte_data.decode("UTF-8")
        request_data_dict = json.loads(request_data)
        request_flag = list(request_data_dict.keys())[0]
        if request_flag == "current_lot":
            return json.dumps(self.current_lot_operation())
        if request_flag == "new_lot":
            request_data_dict = list(request_data_dict.values())[0]
            return json.dumps(self.new_lot_operation(request_data_dict))
        return None

    def new_lot_operation(self, request_data_dict: dict):
        """web 页面创建工单触发的操作."""
        tag_name = self.config["plc_signal_address"]["new_lot"]["tag_name"]
        self.plc.execute_write(tag_name, "bool", True)  # 写入请求开工单
        call_backs = self.get_plc_signal_call_back("new_lot")

        lot_id = request_data_dict.get("lot_id")  # 新的工单号
        old_lot_id = self.get_current_lot_id()
        self.update_current_lot_id(lot_id)  # 更新工单号
        recipe = request_data_dict.get("recipe")  # 新的配方号
        old_recipe = self.get_current_recipe()
        self.update_current_recipe(recipe)  # 更新配方

        if state := self.execute_call_backs(call_backs, time_out=10):
            self.status_variables.get(self.get_sv_id_with_name("track_in_index")).value = 0  # 清空标识
            self.save_current_lot_local(lot_id=lot_id, recipe=recipe)  # 将当前工单, 配方和所有plc上传的配方名保存在本地

        else:
            self.update_current_lot_id(old_lot_id)  # 还原工单
            self.update_current_recipe(old_recipe)  # 还原配方
            self.plc.execute_write(tag_name, "bool", 0)  # 超时了清空信号

        response = {  # 回复web页面请求信息
            "icon_code": 6 if state else 5,
            "message": "New lot success!" if state else "The current status does not allow opening new lot!",
            "current_lot": self.get_current_lot_id(),
            "current_recipe": self.get_current_recipe()
        }
        return response

    def current_lot_operation(self) -> dict:
        """获取当前工单信息, 包含工单名 所有的配方名列表 当前配方名."""
        current_lot_info = {
            "current_lot": self.get_config_value("current_lot").get("lot_id"),
            "recipes": self.get_config_value("current_lot").get("recipes"),
            "current_recipe": self.get_config_value("current_lot").get("current_recipe"),
            "plc_connect_state": self.plc.communication_open()
        }
        return current_lot_info

    # 启动监控plc信号线程
    def start_monitor_plc_thread(self):
        """启动监控 plc 事件信号的线程."""
        def _mes_heart():
            tag_name = self.config["plc_signal_tag_name"]["mes_heart"]["tag_name"]
            while True:
                try:
                    self.plc.execute_write(tag_name, "bool", True, save_log=False)
                    time.sleep(self.get_config_value("mes_heart"))
                    self.plc.execute_write(tag_name, "bool", False, save_log=False)
                    time.sleep(self.get_config_value("mes_heart"))
                except PLCWriteError:
                    self.logger.warning(f"*** plc未连接 *** -> plc地址是: {self.plc.ip}!")
                    if self.plc.communication_open() is False:
                        self.logger.warning("*** plc connect attempt *** -> wait 10s attempt.")
                        time.sleep(10)
                    else:
                        self.logger.warning(f"*** plc connect success*** -> plc地址是: {self.plc.ip}.")
        threading.Thread(target=_mes_heart, daemon=True).start()

        def _monitor_plc_thread(**kwargs):
            self.monitor_plc_address(**kwargs)  # 实时监控plc信号

        plc_signal_dict = self.get_config_value("plc_signal_tag_name", {})
        for signal_name, signal_info in plc_signal_dict.items():
            if signal_info.get("loop", False):  # 实时监控的信号才会创建线程
                thread = threading.Thread(
                    target=_monitor_plc_thread,
                    daemon=True,
                    kwargs=signal_info,
                    name=f"{signal_name}_thread"
                )
                thread.start()

    # 通用函数

    def signal_trigger_event(self, call_back_list: list, signal_info: dict):
        """监控到信号触发事件.

        Args:
            call_back_list (list): 要执行的操作信息列表.
            signal_info (dict): 信号信息.
        """
        if self.get_current_thread_name() == "small_index_thread":
            current_track_in_index = int(self.get_sv_value_with_name("track_in_index"))
            current_track_in_index += 1  # 接收到进站信号,小盒子数量加1
            self.status_variables.get(self.get_sv_id_with_name("track_in_index")).value = str(current_track_in_index)

        self.logger.info(f"{'=' * 40} Get Signal: {signal_info.get('description')}, "
                         f"地址位: {signal_info.get('tag_name')} {'=' * 40}")
        self.execute_call_backs(call_back_list)  # 根据配置文件下的call_back执行具体的操作

        if self.get_current_thread_name() == "upload_recipe_thread":
            self.save_recipe()
            self.save_current_lot_local(self.get_current_lot_id(), self.get_current_recipe())
        self.logger.info(f"{'=' * 40} Signal clear: {signal_info.get('description')} {'=' * 40}")

    def save_recipe(self):
        """保存配方."""
        recipe_id = self.get_sv_value_with_name("upload_recipe_id")
        recipe_name = self.get_sv_value_with_name("upload_recipe_name")
        recipe_id_name = f"{recipe_id}_{recipe_name}"
        recipe_id_name not in self.recipes and self.recipes.append(recipe_id_name)  # pylint: disable=W0106

    def execute_call_backs(self, call_backs: list, time_out=5) -> bool:
        """根据操作列表执行具体的操作.

        Args:
            call_backs (list): 要执行动作的信息列表, 按照列表顺序执行.
            time_out (int): 超时时间.
        """
        for i, call_back in enumerate(call_backs, 1):
            description = call_back.get("description")
            self.logger.info(f"{'-' * 30} Step {i} 开始: {description} {'-' * 30}")
            if call_back.get("operation_type") == "read":
                self.read_operation(call_back)  # 读取plc相关操作
            elif call_back.get("operation_type") == "write":  # write操作
                is_next = self.write_operation(call_back, time_out=time_out)  # 写入plc相关操作
                if not is_next:  # 返回 False, 说明 plc 超时了, 无需进行后面的操作
                    self.logger.info(f"{'-' * 30} Step {i} 结束 Failure: {description} {'-' * 30}")
                    return is_next
            elif call_back.get("operation_type") == "get_photo":
                self.save_upload_data(call_back.get("photo_dir"))  # 保存上传数据
            self.logger.info(f"{'-' * 30} 结束 Success: {description} {'-' * 30}")
        return True

    def monitor_plc_address(self, wait_time=0, **kwargs):
        """实时监控plc信号."""
        while True:
            # noinspection PyBroadException
            try:
                current_value = self.plc.execute_read(kwargs.get("tag_name"), "bool", False)
                # pylint: disable=W0106
                current_value and self.signal_trigger_event(kwargs.get("call_back"), kwargs)  # 监控到bool信号触发事件
                time.sleep(wait_time)
            except Exception:  # pylint: disable=W0718
                pass

    def write_operation(self, call_back: dict, time_out=5) -> bool:
        """写入plc相关操作."""
        tag_name = call_back.get("tag_name")
        data_type = call_back.get("data_type")
        write_value = call_back.get("value")
        if "sv" in str(write_value):
            sv_id = int(write_value.split("_")[-1])
            write_value = self.status_variables.get(sv_id).value

        if premise_tag_name := call_back.get("premise_tag_name"):
            premise_value = call_back.get("premise_value")
            result = self.write_with_condition(
                tag_name, premise_tag_name, premise_value, data_type, write_value, time_out=time_out
            )
            return result
        return self.write_no_condition(tag_name, write_value, data_type)

    def read_operation(self, call_back: dict):
        """读取plc数据, 更新sv."""
        tag_name = call_back.get("tag_name")
        data_type = call_back.get("data_type")
        sv_name = call_back.get("sv_name")
        sv_id = self.get_sv_id_with_name(sv_name)
        plc_value = self.plc.execute_read(tag_name, data_type)
        self.status_variables.get(sv_id).value = plc_value
        if sv_name == "track_out_state" and self.is_mix("track_out"):
            self.status_variables.get(sv_id).value = 0

    # pylint: disable=R0913, disable=R0917
    def write_with_condition(
            self, tag_name, premise_tag_name, premise_value, data_type, write_value, time_out=5) -> bool:
        """Write value with condition.

        Args:
            tag_name (str): 要清空信号的地址位置.
            premise_tag_name (str): 根据这地址位的值来清空信号.
            premise_value (bool): 清空地址的判断值.
            data_type (str): 要写入数据类型.
            write_value (str, int): 要写入的数据.
            time_out (int): 超时时间.
        """
        flag = True
        expect_time = time_out
        self.logger.info(f"*** Start get premise condition value *** -> tag_name: {premise_tag_name}")
        real_premise_value = self.plc.execute_read(premise_tag_name, "bool")
        self.logger.info(f"*** End get premise condition value *** -> real_value: {real_premise_value}, "
                         f"expect_value: {premise_value}")
        if premise_value == real_premise_value:
            self.plc.execute_write(tag_name, data_type, write_value)
        else:
            while time_out:
                self.logger.info(f"*** Start get premise condition value *** -> tag_name: {premise_tag_name}")
                real_premise_value = self.plc.execute_read(premise_tag_name, "bool")
                self.logger.info(
                    f"*** End get premise condition value *** -> real_value: {real_premise_value}, "
                    f"expect_value: {premise_value}"
                )
                if premise_value == real_premise_value:
                    self.plc.execute_write(tag_name, data_type, write_value)
                    break
                time.sleep(1)
                time_out -= 1
                if time_out == 0:
                    flag = False
                    self.logger.error(f"*** plc 超时 *** -> plc 未在 {expect_time}s 内及时回复! clear mes signal")
                    self.plc.execute_write(tag_name, "bool", write_value)
        return flag

    def write_no_condition(self, tag_name, write_value, data_type):
        """向指定标签写入值."""
        self.plc.execute_write(tag_name, data_type, write_value)
        return True

    def get_plc_signal_call_back(self, signal_name) -> list:
        """根据信号名称获取要执行的操作信息."""
        return self.get_config_value("plc_signal_address").get(signal_name)["call_back"]

    def get_current_lot_id(self) -> str:
        """获取当前工单名."""
        return self.get_sv_value_with_name("current_lot_id")

    def get_current_recipe(self) -> str:
        """获取当前配方."""
        return self.get_sv_value_with_name("current_recipe")

    # pylint: disable=R0914
    def get_label_info(self, event_name):
        """获取进站标签信息."""
        label_info = self.get_sv_value_with_name(event_name)
        if event_name == "track_in_label_left" and self.get_sv_value_with_name("track_in_state") == 1:
            # record print label
            self.status_variables.get(self.get_sv_id_with_name("print_label")).value = label_info
        gtin_length = self.get_config_value("gtin_length")
        gtin_code_length = self.get_config_value("gtin_code_length")
        expired_length = self.get_config_value("expired_length")
        expired_code_length = self.get_config_value("expired_code_length")
        lot_length = self.get_config_value("lot_length")
        lot_code_length = self.get_config_value("gtin_code_length")
        gtin_code = label_info[:gtin_code_length]
        gtin = label_info[gtin_code_length:gtin_code_length + gtin_length]
        _length = gtin_code_length + gtin_length + expired_code_length
        expired_code = label_info[gtin_code_length + gtin_length:_length]
        expired = label_info[_length:_length + expired_length]
        lot_code_length_start = _length + expired_length
        lot_code = label_info[lot_code_length_start:lot_code_length_start + lot_code_length]
        lot_length_start = lot_code_length_start + lot_code_length
        lot = label_info[lot_length_start: lot_length_start + lot_length]
        return {
            "QR": label_info,
            "GTIN Code": gtin_code, "GTIN": gtin,
            "EXPIPY Code": expired_code, "Expired Date": self.get_date_str(expired),
            "Lot Code": lot_code, "Lot #": lot
        }

    # pylint: disable=R1705
    def is_mix(self, event_name) -> int:
        """Mix, not in this lot or new lot."""
        label_length = self.get_config_value("label_length")
        if event_name == "track_in":
            real_value = self.get_sv_value_with_name("track_in_label_left")
            if self.get_sv_value_with_name("current_lot_id") in real_value and label_length == len(real_value):
                return 1
            if self.get_sv_value_with_name("current_lot_id") in real_value and label_length != len(real_value):
                return self.get_config_value("new_lot_state_code")
            return 0
        else:
            track_out_state = self.get_config_value("track_out_state")
            real_value = self.get_sv_value_with_name("track_out_label")
            if track_out_state == 63 and self.get_sv_value_with_name("current_lot_id") in real_value:
                return 1
            return 0

    def get_track_in_state(self):
        """根据相机检查结果获取MES反馈结果."""
        track_in_state_left = self.get_sv_value_with_name("track_in_state_left")
        track_in_state_right = self.get_sv_value_with_name("track_in_state_right")
        if {track_in_state_left, track_in_state_right} == {self.get_config_value("track_in_ok")}:
            self.status_variables.get(self.get_sv_id_with_name("track_in_state")).value = 1
            state = "OK"
            mix_num = self.is_mix("track_in")
            if mix_num in (0, 3):
                self.status_variables.get(self.get_sv_id_with_name("track_in_state")).value = mix_num
                state = "NG"

        else:
            self.status_variables.get(self.get_sv_id_with_name("track_in_state")).value = 0
            state = "NG"
        return state

    def get_check_tape_state(self):
        """根据2个相机检查结果获取最终结果."""
        check_state_1 = self.get_sv_value_with_name("check_state_1")
        check_state_2 = self.get_sv_value_with_name("check_state_2")
        check_state_3 = self.get_sv_value_with_name("check_state_3")
        check_state_4 = self.get_sv_value_with_name("check_state_4")
        if {check_state_1, check_state_2, check_state_3, check_state_4} == {1}:
            self.status_variables.get(self.get_sv_id_with_name("check_state")).value = 1
            state = "OK"
        else:
            self.status_variables.get(self.get_sv_id_with_name("check_state")).value = 0
            state = "NG"
        return state

    def update_current_lot_id(self, lot_id):
        """更新当前工单名."""
        self.status_variables.get(self.get_sv_id_with_name("current_lot_id")).value = lot_id

    def update_current_recipe(self, recipe):
        """更新当前配方名."""
        if recipe:
            recipe_id, recipe_name = recipe.split("_")
            self.status_variables.get(self.get_sv_id_with_name("current_recipe_id")).value = int(recipe_id)
            self.status_variables.get(self.get_sv_id_with_name("current_recipe_name")).value = recipe_name
            self.status_variables.get(self.get_sv_id_with_name("current_recipe")).value = recipe

    def save_upload_data(self, photo_dir):
        """保存上传数据."""
        if self.get_current_thread_name() == "track_in_thread":
            self.save_track_in(photo_dir)
        elif self.get_current_thread_name() == "check_tape_result_thread":
            self.save_check_tape(photo_dir)
        elif self.get_current_thread_name() == "track_out_thread":
            self.save_track_out(photo_dir)

    def save_track_in(self, photo_dir):
        """保存track_in上传数据."""
        index = self.get_sv_value_with_name("track_in_index")
        track_in_state = self.get_track_in_state()
        data = {
            index: {
                "Index": index,
                **self.get_label_info("track_in_label_left"),
                "QR Read Result": track_in_state,
                "Label Inspection Result": track_in_state,
                "Label Inspection Failure Reason": self.get_state_reason("track_in"),
                "Label Image Take Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        }
        if not self.get_sv_value_with_name("track_in_state"):
            self.upload_data(
                data=data[index], sheet_name=self.sheet_name, photo_dir=photo_dir,
                base_id=self.base_id, event_name="track_in"
            )
        else:
            self.upload_dict.update(data)
            self.logger.info(f"*** 更新了track_in上传数据 *** -> {data}")

    def get_state_reason(self, event_name) -> str:
        """获取进站失败原因."""
        reason_list = []

        if event_name == "track_in" and self.get_sv_value_with_name("track_in_state") == 0:
            if self.is_mix(event_name):
                reason_list.append(self.get_config_value("ng_reason")["mix"])
            else:
                reason_list = self.append_reason(reason_list, "track_in_state_left")
                reason_list = self.append_reason(reason_list, "track_in_state_right")
        elif event_name == "check_tape" and self.get_sv_value_with_name("check_state") == 0:
            reason_list = self.append_reason(reason_list, "check_state_1")
            reason_list = self.append_reason(reason_list, "check_state_2")
            reason_list = self.append_reason(reason_list, "check_state_3")
            reason_list = self.append_reason(reason_list, "check_state_4")
        return ",".join(reason_list)

    def append_reason(self, reasons, sv_name):
        """Append failure reason."""
        state_num = self.get_sv_value_with_name(sv_name)
        states = self.plc.get_true_bit_with_num(state_num)
        ng_reasons = self.get_config_value("ng_reason")
        for state in states:
            if str(state) in ng_reasons:
                reasons.append(ng_reasons.get(str(state)))
        return reasons

    def save_check_tape(self, photo_dir):
        """保存check_tape上传数据."""
        data = {
            "Tamper Inspection Result": self.get_check_tape_state(),
            "Tamper Inspection Failure Reason": self.get_state_reason("check_tape"),
            "Tamper Image Take Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        current_tape_index = self.get_sv_value_with_name("check_tape_index")
        self.logger.info(f"*** current tape index *** -> {current_tape_index}")
        try:
            self.upload_dict.get(current_tape_index).update(data)
            data = self.upload_dict.pop(current_tape_index)
            self.upload_data(
                data=data, sheet_name=self.sheet_name, photo_dir=photo_dir,
                base_id=self.base_id, event_name="check_tape"
            )
        except AttributeError:
            self.logger.error(f"*** tape index repeat *** -> "
                              f"Current tape index: {current_tape_index} has used, repeated!")
        except Exception as e:  # pylint: disable=W0718
            self.logger.error(f"*** Unknown exception *** -> Exception info: {str(e)}")

    def save_track_out(self, photo_dir):
        """保存track_out上传数据."""

    def save_current_lot_local(self, lot_id="", recipe=""):
        """保存当前的工单, 为了断电重启后读取当前工单和配方."""
        save_lot = {"lot_id": lot_id, "recipes": self.recipes, "current_recipe": recipe}
        self.config["current_lot"] = save_lot
        self.update_config(f"{'/'.join(self.__module__.split('.'))}.conf", self.config)

    def upload_data(self, **kwargs):
        """上传数据."""
        self.logger.info("*** 开始上传数据 ***")

        def _upload_thread(**upload_kwargs):
            date_dir = datetime.now().strftime("%Y-%m-%d")
            data = upload_kwargs.get("data")
            base_id = upload_kwargs.get("base_id")
            sheet_name = upload_kwargs.get("sheet_name")
            event_name = upload_kwargs.get("event_name")
            photo_dir = upload_kwargs.get("photo_dir")
            record_id = self.airtable_instance.create_one_record(base_id, sheet_name, data)
            if event_name == "track_in":
                self.airtable_instance.upload_photo_with_record_id(
                    base_id, record_id, self.get_config_value("airtable")["track_in_left_column"],
                    photo_path=self.get_photo_path(f"{photo_dir}/CCD0/{date_dir}")
                )
                self.airtable_instance.upload_photo_with_record_id(
                    base_id, record_id, self.get_config_value("airtable")["track_in_right_column"],
                    photo_path=self.get_photo_path(f"{photo_dir}/CCD1/{date_dir}")
                )
                self.logger.info("*** 结束上传数据 *** ")
            elif event_name == "check_tape":
                self.airtable_instance.upload_photo_with_record_id(
                    base_id, record_id, self.get_config_value("airtable")["track_in_left_column"],
                    photo_path=self.get_photo_path(f"{self.get_config_value('track_in_dir')}/CCD0/{date_dir}")
                )
                self.airtable_instance.upload_photo_with_record_id(
                    base_id, record_id, self.get_config_value("airtable")["track_in_right_column"],
                    photo_path=self.get_photo_path(f"{self.get_config_value('track_in_dir')}/CCD1/{date_dir}")
                )
                self.airtable_instance.upload_photo_with_record_id(
                    base_id, record_id, self.get_config_value("airtable")["tape_check_left_column"],
                    photo_path=self.get_photo_path(f"{photo_dir}/CCD1_Pos1/{date_dir}")
                )
                self.airtable_instance.upload_photo_with_record_id(
                    base_id, record_id, self.get_config_value("airtable")["tape_check_right_column"],
                    photo_path=self.get_photo_path(f"{photo_dir}/CCD1_Pos2/{date_dir}")
                )
                self.airtable_instance.upload_photo_with_record_id(
                    base_id, record_id, self.get_config_value("airtable")["tape_check_left_column"],
                    photo_path=self.get_photo_path(f"{photo_dir}/CCD2_Pos1/{date_dir}")
                )
                self.airtable_instance.upload_photo_with_record_id(
                    base_id, record_id, self.get_config_value("airtable")["tape_check_right_column"],
                    photo_path=self.get_photo_path(f"{photo_dir}/CCD2_Pos2/{date_dir}")
                )
        threading.Thread(target=_upload_thread, kwargs=kwargs, daemon=True).start()

    @staticmethod
    def get_current_thread_name():
        """获取当前线程名称"""
        return threading.current_thread().name

    @staticmethod
    def get_photo_path(path_dir, index=-1):
        """获取图片路径."""
        photo_name = os.listdir(path_dir)[index]
        return f"{path_dir}/{photo_name}"

    @staticmethod
    def get_date_str(date_str):
        """Get expect date str."""
        if date_str:
            return f"{date_str[:2]}-{date_str[2:4]}-{date_str[4:]}"
        return ""
