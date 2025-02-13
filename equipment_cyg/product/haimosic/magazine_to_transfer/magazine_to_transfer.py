# pylint: skip-file
"""银烧结转盘设备, 将产品从托盘转化到转盘上."""
import time

from inovance_tag.tag_communication import TagCommunication

from equipment_cyg.controller.controller import Controller


# noinspection DuplicatedCode
class MagazineToTransfer(Controller):
    """银烧结转盘设备 class."""

    def __init__(self):
        super().__init__()
        self.temp_save_product = {}
        self.temp_transfer_code = ""
        self.plc = TagCommunication(self.get_dv_value_with_name("plc_ip"))
        self.plc.logger.addHandler(self.file_handler)  # 保存plc日志到文件
        self.plc.communication_open()

        self.save_current_recipe_name_local(self.plc)

        self.enable_equipment()  # 启动MES服务

        self.start_monitor_plc_thread("tag")  # 启动监控plc信号线程

    def _on_rcmd_carrier_in_reply(self, recipe_name: str):
        """Host发送s02f42托盘转盘请求.

        Args:
            recipe_name: 配方名称.
        """
        self.set_dv_value_with_name("eap_recipe_name", recipe_name)

        if recipe_name == self.get_sv_value_with_name("current_recipe_name"):
            self.set_dv_value_with_name("is_allow_carrier_in", 1)
            self.set_dv_value_with_name("match_state", 1)
            self.set_dv_value_with_name("eap_recipe_name", recipe_name)
        else:
            self.set_dv_value_with_name("is_allow_carrier_in", 2)
            self.set_dv_value_with_name("match_state", 2)

        self.send_s6f11("carrier_in_result")

        self.set_dv_value_with_name("reply_flag", True)

    def wait_eap_reply(self, *args, **kwargs):
        """等待EAP回复进站."""
        self.logger.info(args, kwargs)
        self.set_dv_value_with_name("reply_flag", True)
        time_out = 0
        while not self.get_dv_value_with_name("reply_flag"):
            time_out += 1
            self.logger.info("EAP 未回复, 等待 1 秒")
            time.sleep(1)
            if time_out == 5:
                break
        self.set_dv_value_with_name("reply_flag", False)

    def signal_trigger_event(self, call_back_list: list, signal_info: dict, plc_type: str):
        """监控到信号触发事件.

        Args:
            call_back_list (list): 要执行的操作信息列表.
            signal_info (dict): 信号信息.
            plc_type (str): plc类型.
        """
        self.logger.info(f"{'=' * 40} 监控到信号: {signal_info.get('description')} {'=' * 40}")
        self.execute_call_backs(call_back_list, plc_type=plc_type)  # 根据配置文件下的call_back执行具体的操作
        if signal_info.get("description") == "带有产品的托盘进站事件":
            self.set_dv_value_with_name("reply_flag", False)
        if signal_info.get("description") == "产品放入转盘事件":
            self.save_product_link_transfer()

        self.logger.info(f"{'=' * 40} 流程结束: {signal_info.get('description')} {'=' * 40}")

    def save_product_link_transfer(self):
        """保存产品放入托盘信息."""
        transfer_carrier_code = self.get_dv_value_with_name("transfer_carrier_code")
        product_code = self.get_dv_value_with_name("product_code")
        product_state = self.get_dv_value_with_name("product_state")

        if transfer_carrier_code not in self.temp_save_product:
            self.temp_save_product.update({
                transfer_carrier_code: {
                    "product_codes": [product_code],
                    "product_states": [product_state]
                }
            })
        else:
            self.temp_save_product[transfer_carrier_code]["product_codes"].append(product_code)
            self.temp_save_product[transfer_carrier_code]["product_states"].append(product_state)

        if self.get_dv_value_with_name("product_in_transfer_carrier_index") == self.get_tag_name("transfer_carrier_indexes"):
            product_codes_states = self.temp_save_product.pop(transfer_carrier_code)
            product_codes = product_codes_states["product_codes"]
            self.set_dv_value_with_name("product_codes", product_codes)
            product_states = product_codes_states["product_states"]
            self.set_dv_value_with_name("product_states", product_states)
            self.send_s6f11("transfer_carrier_out")

