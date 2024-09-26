"""
EAP->PC: 建立通讯 s1f13

PC->EAP: 控制状态, 0 = Offline, 1 = Online Local, 2 = Online Remote
    ControlState,1,2,0,0,0,0,0
    ControlState,2,2,0,0,0,0,0
    1.设备默认状态是Online Local
    2.一个是 Offline 就是 Offline
    3.一个是 Online Local 就是 Online Local
    4.两个设备都发 Online Remote 后, 设备状态变为 Online Remote

PC->EAP: 上传配方  s7f3
    PPInquireRp,1,S6-11343A,key1&key2&key3&value1&value2&value3,0,0,0,0,0,0
    PPInquireRp,1,S6-11343A,key1&key2&key3&value1&value2&value3,0,0,0,0,0,0
    1.每个设备上传配方时我会判断, 当前配方是否每个设备都上传了, 如果都上传了, 再上传配方给EAP
    2.上传配方后, 假如一台设备又发了这个配方名, 那我还会上传这个配方给EAP

PC->EAP: 下载配方  s7f5
    1.下位机发出 DownloadRecipeInquire,machine_id,recipe_id,0,0,0,0,0
    2.我接收后通过 s7f5 向EAP发出请求
    3.EAP 通过 s7f6 回复配方信息
    {"station_1":{"KeyNames":["key1"],"KeyValues":["value1"]},"station_2":{"KeyNames":["key1"],"KeyValues":["value1"]}}
    4.我收到后分别发给2个设备

EAP->PC: EAP请求配方信息  s7f5

EAP->PC: EAP下发配方前询问
    +-------+------------------------+
    | Value | Description            |
    +=======+========================+
    | 0     | OK                     |
    +-------+------------------------+
    | 1     | Already have           |
    +-------+------------------------+
    | 3     | Invalid PPID           |
    +-------+------------------------+
    | 4     | Busy, try later        |
    +-------+------------------------+
    | 5     | Will not accept        |
    +-------+------------------------+
    1.host通过s7f1发送数据:
        1.如果self.recipes里已有这个配方, 回复1:Already have
        2.如果self.recipes里没有这个配方, 再给两个设备发,PPLoadInquire,0,0,0,0,0,0,0, 询问下位机是否可以下发
            1.两个设备都回复 PPReply,1,OK,0,0,0,0,0 才能回复S7F2 ack=0
            2.否则才能回复S7F2, ack=4 设备正在运行

EAP->PC: Host给PC下发配方  s7f3
    1.host通过s7f3发送数据
    {"station_1":{"KeyNames":["key1"],"KeyValues":["value1"]},"station_2":{"KeyNames":["key1"],"KeyValues":["value1"]}}
    2.将配方保存在self.recipes

EAP->PC: EAP查看设备里的所有配方
    host通过 s7f19 发送请求

EAP->PC: 删除配方
    +-------+------------------------+
    | Value | Description            |
    +=======+========================+
    | 0     | Accepted               |
    +-------+------------------------+
    | 4     | PPID not found         |
    +-------+------------------------+
    host通过 s7f17 发送请求

EAP->PC: EAP查看设备里的当前配方
    host通过 s1f3 发送请求

EAP->PC: 选择要执行的配方
    1.EAP通过S2F41 发送 PPSelect  recipe_id=S6-11343A
    2.我收到后更新当前配方名512的值
    3.将配方下发给两个设备
        DownloadRecipe,1,S6-11343A,key1&key2&key3&value1&value2&value3,0,0,0,0,0
        DownloadRecipe,2,S6-11343A,key1&key2&key3&value1&value2&value3,0,0,0,0,0

PC->EAP: PC回复EAP配方切换成功, 发送配方切换成功事件
    1.两个设备都回复OK, 触发配方切换成功事件, 目前只能回OK
        DownloadRecipeReply,1,OK,0,0,0,0,0
        DownloadRecipeReply,2,OK,0,0,0,0,0

PC->EAP: 点击启动按钮向EAP请求启动, 只要EAP没发 STARTWORKORDER 远程命令, 每次点击都会发3000请求启动事件
    1.等待PC给我发 StartWorkInquire,S6-11343A,0,0,0,0,0,0
    2.给EAP通过S6F11发StartWorkInquire事件

EAP->PC: 可以开始工作 s2f41 
    1.EAP通过S2F41发送 STARTWORKORDER 不带参数, 发送
    2.我收到后立马回复S2F42 ACK=4
    3.然后将 StartWorkOrder,OK,0,0,0,0,0,0 分别发给两个设备
    4.设备收到 StartWorkOrder,OK,0,0,0,0,0,0 即可工作

PC->EAP: 设备状态,1=Auto, 2=Manual, 5=Alarm, 默认是 2
    MachineState,1,1,0,0,0,0,0,0
    1.有一个设备在运行，就是运行
    2.两个设备都是Manual才是Manual
    3.报警和设备状态不相关，不会改变设备的状态，只有下位机发设备状态改变才会改变状态

PC->EAP:
    1.报警 AlarmSet,1,1,I AM ALARM,0,0,0,0
    2.解除报警 AlarmReset,1,1,I AM ALARM,0,0,0,0

PC->EAP: 产品进站
    1.PC发我 TrackIn,frame_sn,0,0,0,0,0,0
    2.我通过S6F11发TrackIn事件
    3.EAP通过S2F41发送 TrackInReply track_in_state=OK 给设备2

PC->EAP: 产品出站
    1.PC发我 TrackOut,frame_sn,SN1&SN2&SN3&NG&NA&SN7&SN8,0,0,0,0,0
    2.我通过S6F11发 TrackOut 事件
    3.EAP通过S2F41发送 TrackOutReply  track_out_state=OK 给设备2
    4.EAP通过S2F41发送 TrackOutReply  track_out_state=NG, mix_sn=12DU1C12,1DU1C13,3DU1C12,29DU1C11,23DU1C14 给设备2
    5.设备2会弹框，操作员将混料SN拿出来

PC->EAP: 复位出站, 发送 ResetNG,frame_sn,0,0,0,0
    1.我通过S6F11发ResetNG事件
    2.EAP通过S2F41发送  ResetNGReply  reset_ng_state=OK 给设备2

PC->EAP: 请求停止工作
    1.设备给我发送  LotEnd,0,0,0,0,0,0,0
    2.给EAP发送S6F11 LotEnd事件
    3.EAP通过S2F41发送  LotEndReply "lot_end_state"=OK
        EAP回复 OK 设备才能停止
"""
import asyncio
import json
import threading
import time

from secsgem.gem import StatusVariable
from secsgem.secs.data_items import ACKC7, ACKC10, ALCD, PPGNT
from secsgem.secs.variables import I4, Array, Base, String

from equipment_cyg.controller.controller import Controller
from equipment_cyg.controller.exception import EquipmentRuntimeError
from equipment_cyg.utils.socket.socket_server_asyncio import CygSocketServerAsyncio


# pylint: disable=W1203, disable=W0612, disable=C0103
# noinspection PyUnresolvedReferences
class TongFuWei(Controller):  # pylint: disable=R0901, disable=R0902, disable=R0904
    """通富微扫码压合设备类."""

    def __init__(self):
        super().__init__()
        self.recipes = self.config.get("current_recipe", {})  # 保存下位机传过来的配方, 设备拥有的所有配方

        self.status_variables.get(512).value = list(self.recipes.keys())[0]  # 上一次pp select的配方, 当前配方

        self.recipe_load_inquire = []  # 设备回复EAP是否可以下发配方状态
        self.recipe_load_reply = {}  # 设备回复EAP是否下载好配方
        self.machine_1_control_state = self.status_variables.get(510).value  # 设备1控制状态默认本地在线
        self.machine_2_control_state = self.status_variables.get(510).value  # 设备2控制状态默认本地在线

        self.machine_1_process_state = self.status_variables.get(511).value  # 设备1运行状态默认停止
        self.machine_2_process_state = self.status_variables.get(511).value  # 设备2运行状态默认停止
        self.socket_server = CygSocketServerAsyncio(self.config.get("socket_server_ip"),
                                                    self.config.get("socket_server_port"))
        self.socket_server.logger.addHandler(self.file_handler)  # 保存下位机日志到文件
        self.start_monitor_labview_thread()  # 启动下位机Socket服务
        self.enable_equipment()  # 启动MES服务

    # 启动监听下位机
    def start_monitor_labview_thread(self):
        """启动供下位机连接的socket服务."""
        self.socket_server.operations_return_data = self.operations_return_data

        def run_socket_server():
            asyncio.run(self.socket_server.run_socket_server())

        thread = threading.Thread(target=run_socket_server, daemon=True)  # 主程序结束这个线程也结束
        thread.start()

    # 监听到下位机请求函数
    # pylint: disable=R0912
    def operations_return_data(self, byte_data) -> str:
        """操作并返回数据."""
        try:
            str_data = self.decode_bytes(byte_data)  # 解析接收的下位机数据
            str_data_list = str_data.split(",")
            monitor_event = str_data_list[0]  # 监控事件名称

            # 控制状态
            if monitor_event == "ControlState":
                self.control_state_change(str_data_list)

            # 报警 - 取消报警
            if monitor_event in ["AlarmSet", "AlarmReset"]:
                self.set_clear_alarm(str_data_list)

            # 设备请求开始
            if monitor_event == "StartWorkInquire":
                self.start_work_inquire()

            # 设备状态变化
            if monitor_event == "MachineState":
                self.machine_state_change(str_data_list)

            # 产品进站
            if monitor_event == "TrackIn":
                self.track_in(str_data)

            # 产品出站
            if monitor_event == "TrackOut":
                self.track_out(str_data)

            # 复位出站
            if monitor_event == "ResetNG":
                self.reset_ng(str_data)

            # 上传配方
            if monitor_event == "PPInquireRp":
                self.upload_recipe(str_data)
                return ""

            # 下载配方
            if monitor_event == "DownloadRecipeInquire":
                self.request_recipe_info(str_data)
                return ""

            # MES下载配方前询问状态, 下位机回复MES
            if monitor_event == "PPReply":
                self.download_recipe_inquire_reply(str_data)

            # 设备是否下载好配方, 下位机回复MES
            if monitor_event == "DownloadRecipeReply":
                self.download_recipe_reply(str_data)

            # 结束工单
            if monitor_event == "LotEnd":
                self.lot_end()

            return "OK"
        except EquipmentRuntimeError as e:
            self.logger.warning(f"***代码报错, 已知异常 *** --> 报错信息是: {e}")
            return ""
        except Exception as e:  # pylint: disable=W0718
            self.logger.warning(f"***代码报错, 未知异常 *** --> 报错信息是: {e}")
            return ""

    # 通用函数
    @staticmethod
    def decode_bytes(byte_data, encodings=None) -> str:
        """解析接收的下位机数据.

        Args:
            byte_data (bytes): 需要解析的数据.
            encodings (list): 解析格式列表, 默认值是 None.

        Returns:
            str: 解析后的数据.

        Raises:
            EquipmentRuntimeError: 无法解析.
        """
        if encodings is None:
            encodings = ['UTF-8', 'GBK']
        for encoding in encodings:
            try:
                return byte_data.decode(encoding)
            except UnicodeDecodeError:
                pass
        raise EquipmentRuntimeError(f"无法解码字节流, 尝试了以下编码格式: {encodings}")

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

    def get_send_to_pc_data(self, replace_data, key=None, origin_data=None):
        """从配置文件下send_to_pc字典里的数据发给下位机."""
        if key:
            origin_data = self.config.get("send_to_pc").get(key, "")
            data = origin_data.replace("$", replace_data)
        else:
            data = origin_data.replace("$", replace_data)
        return data

    def save_current_recipe_local(self, current_recipe_id, current_recipe_info):
        """保存当前的配方, 为了断电重启后读取当前配方."""
        self.config["current_recipe"] = {current_recipe_id: current_recipe_info}
        self.update_config(f'{"/".join(self.__module__.split("."))}.conf', self.config)

    # pylint: disable=R1705
    def get_real_control_state(self, machine_id, control_state) -> int:
        """更新每台设备的控制状态, 获取对外真实的控制状态."""
        setattr(self, f"machine_{machine_id}_control_state", control_state)  # 单个设备控制状态改变
        if control_state == 2 and self.machine_1_control_state == self.machine_2_control_state:
            return control_state
        elif control_state == 1:
            return control_state
        elif control_state == 0:
            return control_state
        return self.status_variables.get(510).value

    def get_real_machine_state(self, machine_id, machine_state) -> int:
        """更新每台设备的运行状态, 获取对外真实的运行状态."""
        setattr(self, f"machine_{machine_id}_process_state", machine_state)  # 单个设备运行状态改变
        if machine_state in [1, 5]:
            return machine_state
        elif machine_state == 2 and self.machine_1_process_state == self.machine_2_process_state:
            return machine_state
        return self.status_variables.get(511).value

    # 通用函数结束

    # 事件函数
    def control_state_change(self, str_data_list):
        """判断对外设备控制状态是否改变, 改变则发送S6F11."""
        machine_id, control_state, *args = str_data_list[1:]
        current_control_state = self.get_real_control_state(machine_id, int(control_state))
        if current_control_state != self.status_variables[510].value:
            self.status_variables[510].value = current_control_state
            self.logger.info(f"***PC->EAP, 触发事件*** 控制状态改变: {current_control_state}")
            self.send_s6f11("ControlState")

    def start_work_inquire(self):
        """设备请求开始工作, 发送S6F11."""
        self.logger.info("***PC->EAP, 触发事件*** --> 询问是否可以开始工作")
        self.send_s6f11("StartWorkInquire")

    def machine_state_change(self, str_data_list):
        """判断设备对外运行状态是否改变, 改变则更新设备运行状态, 同时发送S6F11."""
        machine_id, status_value, = map(int, str_data_list[1:3:])
        current_machine_state = self.get_real_machine_state(machine_id, status_value)
        if current_machine_state != self.status_variables.get(511).value:
            self.status_variables.get(511).value = current_machine_state
            self.logger.info(
                f"***PC->EAP, 触发事件*** --> 设备状态改变, 当前设备状态: {current_machine_state}")
            self.send_s6f11("MachineState")

    def set_clear_alarm(self, str_data_list):
        """通过S5F1发送报警和解除报警."""

        def _alarm_sender():
            monitor_event = str_data_list[0]
            machine_id, alarm_id, alarm_text, *_ = str_data_list[1::]
            alarm_id = I4(alarm_id + machine_id)  # 真实的报警id是在后面拼接machine_id, 然后转成I4
            if monitor_event == "AlarmSet":
                alarm_code = ALCD.EQUIPMENT_SAFETY
                self.logger.info(f"***报警*** --> 设备{machine_id}报警, 报警信息: {alarm_text}")
            else:
                alarm_code = self.config["reset_alarm_code"]
                self.logger.info(f"***解除报警*** --> 解除设备{machine_id}报警, 解除报警信息: {alarm_text}")
            self.send_and_waitfor_response(
                self.stream_function(5, 1)({"ALCD": alarm_code, "ALID": alarm_id, "ALTX": alarm_text})
            )

        threading.Thread(target=_alarm_sender, daemon=True).start()

    def track_in(self, str_data):
        """设备2产品进站事件, 更新frame_sn, 发送S6F11."""
        frame_sn = str_data.split(",")[1]
        self.status_variables.get(514).value = frame_sn
        self.logger.info("***PC->EAP, 触发事件*** --> 产品进站")
        self.send_s6f11("TrackIn")

    def track_out(self, str_data):
        """设备2产品出站事件, 更新wafers_sn, 发送S6F11."""
        frame_sn, wafers_sn_str, *args = str_data.split(",")[1::]
        wafers_sn = wafers_sn_str.split("&")
        self.status_variables.get(515).value = wafers_sn
        self.logger.info("***PC->EAP, 触发事件*** --> 产品出站")
        self.send_s6f11("TrackOut")

    def reset_ng(self, str_data):
        """设备2复位出站, 更新frame_sn, 发送S6F11."""
        frame_sn, *args = str_data.split(",")[1::]
        self.status_variables.get(514).value = frame_sn
        self.logger.info("***PC->EAP, 触发事件*** --> 产品复位出站")
        self.send_s6f11("ResetNG")

    def lot_end(self):
        """PC通知EAP工单结束."""
        self.logger.info("***PC->EAP, 触发事件*** --> 生产结束")
        self.send_s6f11("LotEnd")

    def upload_recipe(self, str_data):
        """PC上传配方给EAP."""
        machine_id, recipe_id, recipe_info, *args = str_data.split(",")[1::]
        recipe_name_value_list = recipe_info.split("&")
        recipe_names = recipe_name_value_list[:int(len(recipe_name_value_list) / 2):]
        recipe_values = recipe_name_value_list[int(len(recipe_name_value_list) / 2)::]
        # 临时保存下位机发过来的配方
        if self.recipes.get(recipe_id):
            self.recipes[recipe_id].update({
                f"station_{machine_id}": {"KeyNames": recipe_names, "KeyValues": recipe_values}
            })
        else:
            self.recipes.update({
                recipe_id: {f"station_{machine_id}": {"KeyNames": recipe_names, "KeyValues": recipe_values}}
            })
        # 判断2个设备是否都上传了配方，如果都上传了配方，再上传配方给EAP
        if len(self.recipes.get(recipe_id)) == 2:
            self.logger.info("***PC->EAP, 上传配方***")
            pp_body = json.dumps(self.recipes[recipe_id])
            self.send_process_program(recipe_id, pp_body)
            return
        if machine_id == "1" and len(self.recipes.get(recipe_id)) == 1:
            replace_data = f"配方 {recipe_id} 未在扫码机上创建, 请先在扫码机创建!"
            self.logger.warning(f"***配方未上传*** --> 将要发送弹框: {replace_data}")
            data = self.get_send_to_pc_data(replace_data, "S10F3")
            time.sleep(1)
            asyncio.create_task(self.asyncio_send_data_to_pc(self.config["client_ip"]["1"], data))
        else:
            self.logger.warning(f"***配方未上传*** --> : 配方 {recipe_id} 未在压合机上创建, 请在压合机创建!")

    def request_recipe_info(self, str_data):
        """向EAP请求配方的详细信息."""
        request_machine_id, recipe_id, *args = str_data.split(",")[1:]
        self.send_and_waitfor_response(self.stream_function(7, 5)(recipe_id))

    def download_recipe_inquire_reply(self, str_data):
        """PC回复EAP是否可以下发配方."""
        machine_id, status, *args = str_data.split(",")[1::]
        self.recipe_load_inquire.append(True if status == "OK" else False)  # pylint: disable=R1719
        if len(self.recipe_load_inquire) == 2:
            if all(self.recipe_load_inquire):
                response = PPGNT.OK
                self.logger.info("***PC->EAP, 回复是否可以下发配方*** --> YES")
            else:
                response = PPGNT.BUSY
                self.logger.info("***PC->EAP, 回复是否可以下发配方*** --> NO, 设备正在运行")
            self.recipe_load_inquire = []
            self.send_response(self.stream_function(7, 2)(response), self.packet.header.system)
            del self.packet  # 使用完后删除
        return "OK".encode("utf-8")

    def download_recipe_reply(self, str_data):
        """PC回复EAP两个设备是否都下载完成配方."""
        machine_id, status, *args = str_data.split(",")[1::]
        if status == "OK":
            self.recipe_load_reply.update({machine_id: True})
        if len(self.recipe_load_reply) == 2:
            self.recipe_load_reply = {}  # 清空两个下位机都切换成功记录
            self.logger.info("******PC->EAP, 触发事件****** --> 配方切换成功")
            self.send_s6f11("DownloadRecipe")

    # 事件函数结束

    # 接收EAP函数
    # pylint: disable=R1710
    def _on_s07f01(self, handler, packet):
        """host发送s07f01,下载配方请求前询问状态, EAP是否可以下载配方 PPLoadInquire.

        1.host通过s7f1发送数据
        2.再给两个设备发,PPLoadInquire,0,0,0,0,0,0,0
        3.两个设备都回复OK才能回复host ack=0
            PPReply,1,OK,0,0,0,0,0
            PPReply,2,OK,0,0,0,0,0
        """
        del handler
        # pylint: disable=W0201
        self.packet = packet  # 保存，等待接收到下位机回复再通过s7f2回复mes
        parser_result = self.get_receive_data(packet)
        recipe_id = parser_result.get("PPID")  # process program id
        if recipe_id in self.recipes:  # 判断配方是否存在, 存在回复 1:Already have
            return self.stream_function(7, 2)(PPGNT.ALREADY_HAVE)
        data = self.get_send_to_pc_data(replace_data=recipe_id, key="S7F1")
        self.logger.info("***下载配方询问*** --> 询问下位机1")
        status_1 = self.send_data_to_pc(self.config["client_ip"]["1"], data)
        self.logger.info("***下载配方询问*** --> 询问下位机2")
        status_2 = self.send_data_to_pc(self.config["client_ip"]["2"], data)
        if not (status_1 and status_2):
            return self.stream_function(7, 2)(PPGNT.WILL_NOT_ACCEPT)

    def _on_s07f03(self, handler, packet):
        """Host给PC下发配方, 保存EAP下发的配方."""
        del handler
        parser_result = self.get_receive_data(packet)
        recipe_id = parser_result.get("PPID")
        recipe_body = json.loads(parser_result.get("PPBODY"))
        self.recipes[recipe_id] = recipe_body  # 保存EAP下发的配方
        return self.stream_function(7, 4)(ACKC7.ACCEPTED)

    def _on_s07f05(self, handler, packet):
        """host请求配方数据."""
        del handler
        parser_result = self.get_receive_data(packet)
        recipe_id = parser_result
        pp_body = json.dumps(self.recipes.get(recipe_id, ""))
        return self.stream_function(7, 6)([recipe_id, pp_body])

    # pylint: disable=R1711
    def _on_s07f06(self, handler, packet):
        """host下发配方数据."""
        del handler
        parser_result = self.get_receive_data(packet)
        recipe_infos = parser_result
        recipe_id, recipe_info = recipe_infos.get("PPID"), recipe_infos.get("PPBODY")
        if recipe_id and recipe_info:
            recipe_info_dict = json.loads(recipe_info)
            for machine, recipe_info in recipe_info_dict.items():
                machine_id = machine[-1]
                key_names = "&".join(recipe_info.get("KeyNames"))
                key_values = "&".join(recipe_info.get("KeyValues"))
                recipe_info = f"DownloadRecipeInquireReply,{machine_id},{recipe_id},{key_names}&{key_values}"
                self.logger.info(f"***EAP->PC, 回复配方信息*** --> {recipe_id}: {recipe_info}")
                self.send_data_to_pc(self.config["client_ip"][machine_id], recipe_info)
        return None

    def _on_s07f17(self, handler, packet):
        """删除配方."""
        del handler
        parser_result = self.get_receive_data(packet)
        recipes_id = parser_result
        for recipe_id in recipes_id:
            if recipe_id in self.recipes:
                self.recipes.pop(recipe_id)
                self.logger.info(f"***删除配方*** --> 成功, 配方 {recipe_id} 已删除")
            else:
                self.logger.info(f"***删除配方*** --> 失败, 配方 {recipe_id} 未找到")
                return self.stream_function(7, 18)(ACKC7.PPID_NOT_FOUND)
        return self.stream_function(7, 18)(ACKC7.ACCEPTED)

    def _on_s07f19(self, handler, packet):
        """查看设备的所有配方."""
        del handler
        recipes_id = []
        for recipe_id, recipe_info in self.recipes.items():
            if len(recipe_info) == 2:
                recipes_id.append(recipe_id)
        return self.stream_function(7, 20)(recipes_id)

    def _on_s10f03(self, handler, packet):
        """host terminal display signal."""
        del handler
        parser_result = self.get_receive_data(packet)
        terminal_id = parser_result.get("TID")
        terminal_text = parser_result.get("TEXT")
        time.sleep(1)
        data = self.get_send_to_pc_data(key="S10F3", replace_data=f"{terminal_id}-{terminal_text}")

        status_1 = self.send_data_to_pc(self.config["client_ip"]["1"], data)
        status_3 = self.send_data_to_pc(self.config["client_ip"]["2"], data)
        if all([status_1, status_3]):
            return self.stream_function(10, 4)(ACKC10.ACCEPTED)
        return self.stream_function(10, 4)(3)  # 其他错误

    # pylint: disable=W0237
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
            return status_variable.value_type(String, status_variable.value)
        return status_variable.value_type(status_variable.value)

    # 远程命令函数
    def _on_rcmd_PPSelect(self, **kwargs):
        """收到命令后更新当前设备配方名(512), 将配方分别发给两个设备."""
        recipe_id = kwargs.get("recipe_id")
        self.status_variables.get(512).value = recipe_id
        recipe_info = self.recipes.get(recipe_id, {})
        self.save_current_recipe_local(recipe_id, recipe_info)
        origin_data = self.remote_commands.get("PPSelect").to_pc
        # 接收到切换配方请求，给下位机发送要切换的配方，等待下位机回复触发切换成功事件
        for machine, recipe_info in self.recipes.get(recipe_id, {}).items():
            machine_id = machine[-1]
            key_names = "&".join(recipe_info.get("KeyNames"))
            key_values = "&".join(recipe_info.get("KeyValues"))
            replace_data = f"{machine_id},{recipe_id},{key_names}&{key_values}"
            data = self.get_send_to_pc_data(replace_data=replace_data, origin_data=origin_data)
            self.send_data_to_pc(self.config["client_ip"][machine_id], data)

    def _on_rcmd_STARTWORKORDER(self, **kwargs):  # pylint: disable=W0613
        """收到命令后给两个设备发出StartWorkOrder,ok,0,0,0,0,0,0,."""
        self.logger.info("***EAP->PC, 开始*** --> 开始工作")
        data = self.remote_commands.get("STARTWORKORDER").to_pc
        self.send_data_to_pc(self.config["client_ip"]["1"], data)
        self.send_data_to_pc(self.config["client_ip"]["2"], data)

    def _on_rcmd_TrackInReply(self, **kwargs):
        """收到命令后给两个设备发出TrackInReply,OK or NG,0,0,0,0,0,0."""
        track_in_state = kwargs.get("track_in_state")
        data = self.remote_commands.get("TrackInReply").to_pc.get(track_in_state, "NG")
        self.send_data_to_pc(self.config["client_ip"]["2"], data)

    def _on_rcmd_TrackOutReply(self, **kwargs):
        """收到命令后给两个设备发出TrackOut,OK or NG,0,0,0,0,0,0."""
        track_out_state = kwargs.get("track_out_state")
        data = self.remote_commands.get("TrackOutReply").to_pc[track_out_state]
        if track_out_state != "OK":
            wafers_sn = kwargs.get("mix_sn", "").replace(",", "&")
            data = data.replace("$", wafers_sn)
        self.send_data_to_pc(self.config["client_ip"]["2"], data)

    def _on_rcmd_ResetNGReply(self, **kwargs):
        """收到命令后给两个设备发出ResetNGReply,OK or NG,0,0,0,0."""
        reset_ng_state = kwargs.get("reset_ng_state")
        data = self.remote_commands.get("ResetNGReply").to_pc.get(reset_ng_state, "NG")
        self.send_data_to_pc(self.config["client_ip"]["2"], data)

    def _on_rcmd_LotEndReply(self, **kwargs):
        """收到命令后给两个设备发出ResetNGReply,OK,0,0,0,0."""
        lot_end_state = kwargs.get("lot_end_state")
        data = self.remote_commands.get("LotEndReply").to_pc.get(lot_end_state, "NG")
        self.send_data_to_pc(self.config["client_ip"]["1"], data)
        self.send_data_to_pc(self.config["client_ip"]["2"], data)
