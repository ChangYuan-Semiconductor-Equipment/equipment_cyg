# pylint: skip-file
"""中芯二次焊中间设备."""
import asyncio
import time

from secsgem.gem import StatusVariable
from secsgem.secs.data_items import ACKC10
from secsgem.secs.variables import Base, Array, U4
from socket_cyg.socket_server_asyncio import CygSocketServerAsyncio

from equipment_cyg.controller.controller import Controller


# noinspection DuplicatedCode
class HpdCenter(Controller):
    """中芯二次焊中间设备 class."""

    def __init__(self):
        super().__init__()

        self.socket_server = CygSocketServerAsyncio(
            self.get_dv_value_with_name("socket_server_ip"), self.get_dv_value_with_name("socket_server_port")
        )
        self.socket_server.logger.addHandler(self.file_handler)  # 保存下位机日志到文件
        self.start_monitor_labview_thread()  # 启动下位机Socket服务

        self.enable_equipment()  # 启动MES服务

    def send_data_to_pc(self, client_ip: str, data: str) -> bool:
        """发送数据给下位机.

        Args:
            client_ip (str): 接收数据的设备ip地址.
            data (str): 要发送的数据

        Return:
            bool: 是否发送成功.
        """
        status = True
        client_connection = self.socket_server.clients.get(client_ip)
        if client_connection:
            byte_data = str(data).encode("utf-8")
            asyncio.run(self.socket_server.socket_send(client_connection, byte_data))
        else:
            self.logger.warning(f"***发送*** --> 发送失败, 设备{client_ip}, 未连接")
            status = False
        return status

    async def asyncio_send_data_to_pc(self, client_ip: str, data: str) -> bool:
        """发送数据给下位机.

        Args:
            client_ip (str): 接收数据的设备ip地址.
            data (str): 要发送的数据

        Return:
            bool: 是否发送成功.
        """
        status = True
        client_connection = self.socket_server.clients.get(client_ip)
        if client_connection:
            byte_data = str(data).encode("utf-8")
            await self.socket_server.socket_send(client_connection, byte_data)
        else:
            self.logger.warning(f"***发送*** --> 发送失败, 设备{client_ip}, 未连接")
            status = False
        return status

    def current_recipe_name(self, data_dict: dict):
        self.logger.info("labview 发来了 current_recipe_name, 带有数据: %s", data_dict)
        self.save_current_recipe_name_local_socket()

    def pp_select_feed(self, data_dict: dict):
        self.logger.info("labview 发来了 pp_select_feed, 带有数据: %s", data_dict)
        if self.get_dv_value_with_name("pp_select_state") == 1:
            self.set_sv_value_with_name("current_recipe_name", self.get_dv_value_with_name("pp_select_recipe_name"))
        self.send_s6f11("pp_select")

    def dbc_code_link_request(self, data_dict: dict):
        self.logger.info("labview 发来了 dbc_code_link_request, 带有数据: %s", data_dict)
        reply = "dbc_code_link_reply,1@"
        asyncio.create_task(self.asyncio_send_data_to_pc(self.get_dv_value_with_name("socket_server_ip"), reply))

    def carrier_in(self, data_dict: dict):
        self.logger.info("labview 发来了 carrier_in, 带有数据: %s", data_dict)
        self.send_s6f11("carrier_in")

    def carrier_out(self, data_dict: dict):
        self.logger.info("labview 发来了 carrier_out, 带有数据: %s", data_dict)
        self.send_s6f11("carrier_out")


    def dbc_link(self, data_dict: dict):
        self.logger.info("labview 发来了 dbc_link, 带有数据: %s", data_dict)

    def upload_recipe(self, data_dict: dict):
        self.logger.info("labview 发来了 upload_recipe, 带有数据: %s", data_dict)
        self.save_recipe_socket()

    def on_sv_value_request(self, sv_id: Base, status_variable: StatusVariable) -> Base:
        """Get the status variable value depending on its configuration.

        Args:
            sv_id (Base): The id of the status variable encoded in the corresponding type.
            status_variable (StatusVariable): The status variable requested.

        Returns:
            The value encoded in the corresponding type
        """
        self.send_data_to_pc(self.get_dv_value_with_name("socket_server_ip"), f"current_recipe_name@")
        time.sleep(1)
        del sv_id
        # noinspection PyTypeChecker
        if issubclass(status_variable.value_type, Array):
            return status_variable.value_type(U4, status_variable.value)
        return status_variable.value_type(status_variable.value)

    def _on_s07f19(self, handler, packet):
        """Host查看设备的所有配方."""
        del handler
        recipes = [recipe_name for recipe_name in list(self.config["recipes"].keys())]
        return self.stream_function(7, 20)(recipes)

    def _on_rcmd_pp_select(self, recipe_name: str):
        """Host发送s02f41配方切换.

        Args:
            recipe_name (str): 要切换的配方name.
        """
        self.set_dv_value_with_name("pp_select_recipe_name", recipe_name)

        self.send_data_to_pc(self.get_dv_value_with_name("socket_server_ip"), f"pp_select,{recipe_name}@")

    def _on_rcmd_dbc_in_request_reply(self, state: int):
        """Host发送s02f42托盘转盘请求.

        Args:
            state: 状态码.
        """
        reply = f"dbc_code_link_reply,{str(state)}@"
        self.send_data_to_pc(self.get_dv_value_with_name("socket_server_ip"), reply)

    def _on_s10f03(self, handler, packet):
        """Host发送弹框信息显示."""
        del handler
        parser_result = self.get_receive_data(packet)
        terminal_id = parser_result.get("TID")
        self.logger.info("terminal_id: %s", terminal_id)
        terminal_text = parser_result.get("TEXT")
        self.logger.info("terminal_text: %s", terminal_text)
        data = f"display,{terminal_text}@"
        self.send_data_to_pc(self.get_dv_value_with_name("socket_server_ip"), data)

        return self.stream_function(10, 4)(ACKC10.ACCEPTED)