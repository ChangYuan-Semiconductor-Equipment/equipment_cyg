# pylint: skip-file
"""
中芯二次焊2010设备.
    1.键合托盘不卡控直接进站, 直接拿基板放在大托盘.
    2.大托盘进站卡控, 一个工单大托盘只能进站一次
    3.每放一个基板上报 EAP
"""
from inovance_tag.tag_communication import TagCommunication

from equipment_cyg.controller.controller import Controller


# noinspection DuplicatedCode
class Hpd2010(Controller):
    """中芯二次焊2010设备 class."""

    def __init__(self):
        super().__init__()

        self.plc = TagCommunication(self.get_dv_value_with_name("plc_ip"))
        self.plc.logger.addHandler(self.file_handler)  # 保存plc日志到文件
        self.plc.communication_open()

        self.save_current_recipe_name_local(self.plc)

        self.enable_equipment()  # 启动MES服务

        self.start_monitor_plc_thread("tag")  # 启动监控plc信号线程

    def _on_rcmd_carrier_in_request_reply(self, state: int):
        """Host发送s02f42托盘转盘请求.

        Args:
            state: 状态码.
        """
        self.set_dv_value_with_name("is_allow_carrier_in", int(state))
        self.set_dv_value_with_name("reply_flag", True)
