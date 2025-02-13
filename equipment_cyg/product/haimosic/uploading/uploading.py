# pylint: skip-file
"""银烧结上料设备."""
import asyncio
import json
import threading
import time
from typing import Optional

from inovance_tag.tag_communication import TagCommunication
from socket_cyg.socket_server_asyncio import CygSocketServerAsyncio

from equipment_cyg.controller.controller import Controller


# noinspection DuplicatedCode
class Uploading(Controller):
    """银烧结上料设备 class."""

    def __init__(self):
        super().__init__()
        self.socket_server = CygSocketServerAsyncio("127.0.0.1", 9000)
        self.socket_server.logger.addHandler(self.file_handler)  # 保存socket日志到文件
        self.start_socket_server_thread()  # 启动接收web请求的socket服务

        self.temp_save_product = {}

        self.plc = TagCommunication(self.get_dv_value_with_name("plc_ip"))
        self.plc.logger.addHandler(self.file_handler)  # 保存plc日志到文件
        self.plc.communication_open()

        self.save_current_recipe_name_local(self.plc)

        self.enable_equipment()  # 启动MES服务

        self.start_monitor_plc_thread("tag")  # 启动监控plc信号线程

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
        request_key = list(request_data_dict.keys())[0]
        request_value_dict = list(request_data_dict.values())[0]
        if request_key == "new_lot":
            # self.plc.execute_write(self.get_tag_name("lot_state"), "int", 3)
            # self.plc.execute_write(self.get_tag_name("lot_quantity"), "dint", 1000)
            self.set_sv_value_with_name("current_lot_state", 1)
            self.set_sv_value_with_name("current_lot_name", request_value_dict["lot_name"])
            self.save_lot()
            self.send_s6f11("new_lot")
        if request_key == "end_lot":
            self.set_sv_value_with_name("current_lot_state", 2)
            self.send_s6f11("end_lot")

        current_lot_info = {
            "current_lot_name": self.get_sv_value_with_name("current_lot_name"),
            "current_lot_state": self.get_sv_value_with_name("current_lot_state"),
        }
        return json.dumps(current_lot_info)

    def save_lot(self):
        """保存工单."""
        self.config["status_variable"]["current_lot_name"]["value"] = self.get_sv_value_with_name("current_lot_name")
        self.config["status_variable"]["current_lot_state"]["value"] = self.get_sv_value_with_name("current_lot_state")
        self.update_config(f"{'/'.join(self.__module__.split('.'))}.json", self.config)

    def _on_rcmd_carrier_out_reply(self, state):
        """Host回复托盘是否可以出站.

        Args:
            state (str): 出站结果, 1: 可以出站, 2: 不允许出站.
        """
        self.set_dv_value_with_name("carrier_out_state", int(state))
        self.set_dv_value_with_name("carrier_out_reply_flag", True)

    def signal_trigger_event(self, call_back_list: list, signal_info: dict, plc_type: str):
        """监控到信号触发事件.

        Args:
            call_back_list (list): 要执行的操作信息列表.
            signal_info (dict): 信号信息.
            plc_type (str): plc类型.
        """
        self.logger.info(f"{'=' * 40} 监控到信号: {signal_info.get('description')} {'=' * 40}")
        self.execute_call_backs(call_back_list, plc_type=plc_type)  # 根据配置文件下的call_back执行具体的操作
        if signal_info.get("description") in ["左产品放入托盘事件", "右产品放入托盘事件"]:
            self.save_product_link_carrier()

        if signal_info.get("description") == "带有产品的托盘请求出站事件":
            self.logger.info("带有产品的托盘出站.")
            self.send_carrier_out_event()
            self.set_dv_value_with_name("carrier_out_reply_flag", False)

        self.logger.info(f"{'=' * 40} 流程结束: {signal_info.get('description')} {'=' * 40}")

    def send_carrier_out_event(self):
        """发送带有产品的出站请求事件."""
        carrier_code_out = self.get_dv_value_with_name("carrier_code_out")
        product_info = self.temp_save_product.pop(carrier_code_out)
        product_codes = product_info.get("product_codes")
        product_states = product_info.get("product_states")
        self.set_dv_value_with_name("product_codes", product_codes)
        self.set_dv_value_with_name("product_states", product_states)
        self.send_s6f11("carrier_out_request")

    def save_product_link_carrier(self):
        """保存产品放入托盘信息."""
        carrier_code = self.get_dv_value_with_name("carrier_code")
        product_code = self.get_dv_value_with_name("product_code")
        product_state = self.get_dv_value_with_name("product_state")

        if carrier_code not in self.temp_save_product:
            self.temp_save_product.update({
                carrier_code: {
                    "product_codes": [product_code],
                    "product_states": [product_state]
                }
            })
        else:
            self.temp_save_product[carrier_code]["product_codes"].append(product_code)
            self.temp_save_product[carrier_code]["product_states"].append(product_state)

    def wait_eap_reply(self, *args, **kwargs):
        """等待EAP回复进站."""
        self.logger.info(args, kwargs)
        self.set_dv_value_with_name("carrier_out_reply_flag", True)

        time_out = 0
        while not self.get_dv_value_with_name("carrier_out_reply_flag"):
            time_out += 1
            self.logger.info("EAP 未回复, 等待 1 秒")
            time.sleep(1)
            if time_out == 5:
                break
        self.set_dv_value_with_name("carrier_out_reply_flag", False)
