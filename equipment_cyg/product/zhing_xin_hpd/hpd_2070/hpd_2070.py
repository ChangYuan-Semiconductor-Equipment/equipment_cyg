# pylint: skip-file
"""
中芯二次焊2070设备.
    1.键合托盘不管控, 直接允许进站
    2.扫描大托盘码EAP回复每个穴位的基板状态, 0: 无基板, 1: 有基板, 5: 此工单最后一个基板
"""
from inovance_tag.tag_communication import TagCommunication

from equipment_cyg.controller.controller import Controller


# noinspection DuplicatedCode
class Hpd2070(Controller):
    """中芯二次焊2070设备 class."""

    def __init__(self):
        super().__init__()

        self.plc = TagCommunication(self.get_dv_value_with_name("plc_ip"))
        self.plc.logger.addHandler(self.file_handler)  # 保存plc日志到文件
        self.plc.communication_open()

        self.save_current_recipe_name_local(self.plc)

        self.enable_equipment()  # 启动MES服务

        self.start_monitor_plc_thread("tag")  # 启动监控plc信号线程

    def _on_rcmd_carrier_in_request_reply(self, state: int, product_codes, product_states, limit_1_codes, limit_2_codes):
        """Host发送s02f42托盘转盘请求.

        Args:
            state: 状态码.
        """
        self.set_dv_value_with_name("is_allow_carrier_in", int(state))
        self.set_dv_value_with_name("reply_flag", True)
