# pylint: skip-file
"""银烧结转盘设备, 将产品从转盘转化到托盘上."""
from inovance_tag.tag_communication import TagCommunication

from equipment_cyg.controller.controller import Controller


# noinspection DuplicatedCode
class TransferToMagazine(Controller):
    """银烧结转盘设备, 将产品从转盘转化到托盘上 class."""

    def __init__(self):
        super().__init__()

        self.plc = TagCommunication(self.get_dv_value_with_name("plc_ip"))
        self.plc.logger.addHandler(self.file_handler)  # 保存plc日志到文件
        self.plc.communication_open()

        self.plc.execute_write("Application.gvl_OPMODE01_MES.mes2plc.geneal.Lot_status", "int", 3)
        self.plc.execute_write("Application.gvl_OPMODE01_MES.mes2plc.geneal.Lot_quantity", "int", 1000)

        self.save_current_recipe_name_local(self.plc)

        self.enable_equipment()  # 启动MES服务

        self.start_monitor_plc_thread("tag")  # 启动监控plc信号线程

    def _on_rcmd_transfer_carrier_in_request(self, state: int, product_infos: str):
        """Host发送s02f42托盘转盘请求.

        Args:
            state: 状态码.
            product_infos: 产品信息.
        """
        self.set_dv_value_with_name("is_allow_magazine_in", int(state))

        product_infos = product_infos.split(",")
        for product_info in product_infos:
            product_code, product_state, product_index = product_info.split("_")

            product_codes = self.get_dv_value_with_name("product_codes")
            product_codes.append(product_code)
            self.set_dv_value_with_name("product_codes", product_codes)

            product_states = self.get_dv_value_with_name("product_states")
            product_states.append(product_state)
            self.set_dv_value_with_name("product_states", product_states)

        self.set_dv_value_with_name("reply_flag", True)


