"""塞米控印刷线体."""
import asyncio
import json
import threading
from typing import Optional

from mysql_api.mysql_database import MySQLDatabase
from mysql_table_model import semikron_line
from socket_cyg.socket_server_asyncio import CygSocketServerAsyncio

from equipment_cyg.controller.host_controller import HostController


class SemikronLine(HostController):
    """SemikronLine class."""

    def __init__(self):
        super().__init__()
        self.current_lot_name = ""
        self.current_article_name = ""
        self.current_lot_state = 2

        self.socket_server = CygSocketServerAsyncio("127.0.0.1", 8000)
        self.socket_server.logger.addHandler(self.file_handler)  # 保存socket日志到文件
        self.start_socket_server_thread()  # 启动接收web请求的socket服务

        self.mysql = MySQLDatabase(
            self.get_config_value("user_name", "cyg", parent_name="mysql"),
            self.get_config_value("password", "liuwei.520", parent_name="mysql")
        )

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
            self.current_lot_state = 1
            self.current_lot_name = request_value_dict["lot_name"]
            self.current_article_name = request_value_dict["article_name"]

            print_paint_instance = getattr(self, "host_handler_print_paint")
            # print_paint_instance.send_remote_command("PPSELECT", [["Recipe_Name", "Mini1"]])

            print_solder_paste_instance = getattr(self, "host_handler_print_solder_paste")
            # print_solder_paste_instance.send_remote_command("PPSELECT", [["Recipe_Name", "Mini1"]])
        if request_key == "end_lot":
            self.current_lot_state = 2

        current_lot_info = {
            "current_lot_name": self.current_lot_name,
            "current_lot_state": self.current_lot_state,
            "current_article_name": self.current_article_name
        }
        return json.dumps(current_lot_info)

    def _on_event_collection_event_received(self, data):
        """接收到设备发来的事件进行处理."""
        peer = data.get("peer")
        equipment_ip = peer.settings.address
        equipment_port = peer.settings.port
        equipment_name = self.get_equipment_name_with_ip(equipment_ip)

        self.logger.info("收到设备发来的事件: %s %s %s", equipment_name, equipment_ip, equipment_port)
        ce_id = data.get("ceid").get()
        self.logger.info("事件id: %s", ce_id)
        values = data.get("values")
        self.logger.info("事件报告的值: %s", values)

        data_dict = self.get_data_of_add_to_database(equipment_name, values)
        self.logger.info("整理后的值: %s", data_dict)

        carrier_dcbs = data_dict.pop("carrier_dcbs").split(",")
        carrier_code, dcb_codes= carrier_dcbs[0], carrier_dcbs[1::]

        table_model = self.get_table_model_with_name(semikron_line, equipment_name)

        for dcb_code_index, dcb_code in enumerate(dcb_codes, 1):
            real_data = {
                **data_dict, "carrier_code": carrier_code, "dcb_code": dcb_code, "dcb_code_index": dcb_code_index
            }
            self.logger.info("写入一行数据: %s", real_data)
            self.mysql.add_data(table_model, real_data)
