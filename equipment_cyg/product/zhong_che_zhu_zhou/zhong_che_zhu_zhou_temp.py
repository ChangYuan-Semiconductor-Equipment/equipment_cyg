# pylint: skip-file
import threading
import time
from typing import Union

from equipment_cyg.controller.controller import Controller
from equipment_cyg.utils.plc.exception import PLCRuntimeError
from equipment_cyg.utils.plc.tag_communication import TagCommunication
from equipment_cyg.utils.plc.tag_type_enum import TagTypeEnum
from suds.client import Client
from suds.xsd.doctor import ImportDoctor, Import


class EapWebService:
    url = "http://10.96.140.135:50302/BPSToMES.asmx?wsdl"
    imp = Import("http://www.w3.org/2001/XMLSchema", location="http://www.w3.org/2001/XMLSchema.xsd")
    imp.filter.add("ttp://WebXml.com.cn/")
    doctor = ImportDoctor(imp)

    def __init__(self):
        self.client = Client(EapWebService.url, doctor=EapWebService.doctor)

    def get_product_type(self, product_sn: str):
        product_type_map = {
            "A": 1,
            "B": 2,
            "C": 3
        }
        result = self.client.service.MaterialLine(**{"materialName": product_sn})
        # noinspection PyBroadException
        try:
            product_type = product_type_map.get(str(result.Data))
        except Exception:
            product_type = 9
        return product_type
        # return 2


class ZhongCheZhuZhouTemp(Controller):
    def __init__(self):
        super().__init__()
        self.plc = TagCommunication(self.get_inovance_dll_path(), self.get_config_value("plc_ip"))
        self.plc.logger.addHandler(self.file_handler)  # 保存plc日志到文件
        self.eap_web_service = EapWebService()

        self.enable_equipment()  # 启动MES服务

        self.start_monitor_plc_thread()  # 启动监控plc信号线程

    def start_monitor_plc_thread(self):
        """启动监控 plc 信号的线程."""
        if self.plc.communication_open():
            self.logger.warning(f"*** First connect to plc success *** -> plc地址是: {self.plc.ip}.")
        else:
            self.logger.warning(f"*** First connect to plc failure *** -> plc地址是: {self.plc.ip}.")
        self.bool_signal_thread()  # bool类型信号线程

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
                current_value and self.signal_trigger_event(kwargs.get("call_back"), kwargs)  # 监控到bool信号触发事件
                time.sleep(wait_time)
            except Exception:
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
    def execute_call_backs(self, call_backs: list, time_out=5):
        """根据操作列表执行具体的操作.

        Args:
            call_backs (list): 要执行动作的信息列表, 按照列表顺序执行.
            time_out (int): 超时时间.

        Raises:
            PLCRuntimeError: 在执行配置文件下的步骤时出现异常.
        """
        for i, call_back in enumerate(call_backs, 1):
            description = call_back.get("description")
            self.logger.info(f"{'-' * 30} Step {i} 开始: {description} {'-' * 30}")
            if call_back.get("operation_type") == "read":
                self.read_operation_update_sv(call_back)  # 读取 plc 地址位更新sv
            elif call_back.get("operation_type") == "write":  # write操作
                self.write_operation(call_back, time_out=time_out)  # 写入plc相关操作
            elif call_back.get("operation_type") == "ask_eap":
                self.ask_eap_update_sv()  # 询问eap产品流线, 更新sv

            self.logger.info(f"{'-' * 30} 结束 Success: {description} {'-' * 30}")

    def ask_eap_update_sv(self):
        """询问eap后更新sv值."""
        product_type_value = self.eap_web_service.get_product_type(self.get_sv_value_with_name("track_in_product_sn"))
        self.set_sv_value_with_name("product_type", product_type_value)

    def read_operation_update_sv(self, call_back: dict, time_out=5):
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
            self.set_sv_value_with_name(call_back.get("sv_name"), plc_value)
        else:
            if isinstance(tag_name, list):
                self.set_sv_value_with_name("track_out_pins_state", [])
                for _tag_name in tag_name:
                    plc_value = self.plc.execute_read(_tag_name, data_type)
                    self.status_variables.get(self.get_sv_id_with_name("track_out_pins_state")).value.append(plc_value)
            elif isinstance(tag_name, str):
                plc_value = self.plc.execute_read(tag_name, data_type).strip()
                self.set_sv_value_with_name(call_back.get("sv_name"), plc_value)

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
        real_premise_value = self.plc.execute_read(premise_tag_name, TagTypeEnum.BOOL.value)
        self.logger.info(f"*** End get premise condition value *** -> real_value: {real_premise_value}, "
                         f"expect_value: {premise_value}")
        if premise_value == real_premise_value:
            return self.plc.execute_read(tag_name, data_type)
        while time_out:
            time.sleep(1)
            self.logger.info(f"*** Start get premise condition value *** -> tag_name: {premise_tag_name}")
            real_premise_value = self.plc.execute_read(premise_tag_name, "bool")
            self.logger.info(
                f"*** End get premise condition value *** -> real_value: {real_premise_value}, "
                f"expect_value: {premise_value}"
            )
            if premise_value == real_premise_value:
                break
            time_out -= 1
            if time_out == 0:
                self.logger.error(f"*** plc 超时 *** -> plc 未在 {expect_time}s 内及时回复!")
        return self.plc.execute_read(tag_name, data_type)

    def write_operation(self, call_back: dict, time_out=5):
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
        real_premise_value = self.plc.execute_read(premise_tag_name, TagTypeEnum.BOOL.value)
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
                    break
                time.sleep(1)
                time_out -= 1
                if time_out == 0:
                    self.logger.error(f"*** plc 超时 *** -> plc 未在 {expect_time}s 内及时回复! clear mes signal")
            self.plc.execute_write(tag_name, "bool", write_value)

    def write_no_condition(self, tag_name: str, write_value: Union[int, str, bool], data_type: str):
        """根据 tag_name 写入指定类型的值.

        Args:
            tag_name (str): 标签名称.
            write_value (Union[int, str, bool]): 要写入的值.
            data_type (str): 要写入值的类型.
        """
        self.plc.execute_write(tag_name, data_type, write_value)
