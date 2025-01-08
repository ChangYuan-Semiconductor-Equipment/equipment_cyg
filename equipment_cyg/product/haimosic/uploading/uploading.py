# pylint: skip-file
"""银烧结上料设备."""
from inovance_tag.tag_communication import TagCommunication

from equipment_cyg.controller.controller import Controller


# noinspection DuplicatedCode
class Uploading(Controller):
    """银烧结上料设备 class."""

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

    def _on_rcmd_pp_select(self, recipe_name):
        """Host发送s02f41配方切换.

        Args:
            recipe_name (str): 要切换的配方 name.
        """
        recipe_id, recipe_name = self.get_recipe_id_name(recipe_name, self.recipes).split("_")
        self.set_dv_value_with_name("pp_select_recipe_id", int(recipe_id))
        self.set_dv_value_with_name("pp_select_recipe_name", recipe_name)

        self.execute_call_backs(self.get_callback_tag("pp_select"), "tag")

        # 切换成功, 更新当前配方id_name, 保存当前配方
        if self.get_dv_value_with_name("current_recipe_id") == int(recipe_id):
            self.set_dv_value_with_name("pp_select_state", 1)
            self.save_current_recipe_name_local(self.plc, recipe_name)
        else:
            self.set_dv_value_with_name("pp_select_state", 2)
        self.send_s6f11("pp_select")  # 触发 pp_select 事件
