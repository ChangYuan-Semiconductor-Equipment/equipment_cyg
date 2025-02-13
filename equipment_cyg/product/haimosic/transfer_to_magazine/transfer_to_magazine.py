# pylint: skip-file
"""银烧结转盘设备, 将产品从转盘转化到托盘上."""
import time

from inovance_tag.tag_communication import TagCommunication

from equipment_cyg.controller.controller import Controller


# noinspection DuplicatedCode
class TransferToMagazine(Controller):
    """银烧结转盘设备, 将产品从转盘转化到托盘上 class."""

    def __init__(self):
        super().__init__()
        self.temp_save_product = {}

        self.plc = TagCommunication(self.get_dv_value_with_name("plc_ip"))
        self.plc.logger.addHandler(self.file_handler)  # 保存plc日志到文件
        self.plc.communication_open()

        self.save_current_recipe_name_local(self.plc)

        self.enable_equipment()  # 启动MES服务

        self.start_monitor_plc_thread("tag")  # 启动监控plc信号线程

    def _on_rcmd_transfer_carrier_in_reply(self, recipe_name: str):
        """Host发送s02f42托盘转盘请求.

        Args:
            recipe_name: 配方名称.
        """
        if recipe_name == self.get_sv_value_with_name("current_recipe_name"):
            self.set_dv_value_with_name("is_allow_magazine_in", 1)
        else:
            self.set_dv_value_with_name("is_allow_magazine_in", 2)
        self.set_dv_value_with_name("reply_flag", True)

    def signal_trigger_event(self, call_back_list: list, signal_info: dict, plc_type: str):
        """监控到信号触发事件.

        Args:
            call_back_list (list): 要执行的操作信息列表.
            signal_info (dict): 信号信息.
            plc_type (str): plc类型.
        """
        self.logger.info(f"{'=' * 40} 监控到信号: {signal_info.get('description')} {'=' * 40}")
        self.execute_call_backs(call_back_list, plc_type=plc_type)  # 根据配置文件下的call_back执行具体的操作
        if signal_info.get("description") == "带有产品的转盘进站事件":
            self.set_dv_value_with_name("reply_flag", False)
        if signal_info.get("description") == "产品放入托盘事件":
            self.save_product_link_carrier()

        self.logger.info(f"{'=' * 40} 流程结束: {signal_info.get('description')} {'=' * 40}")

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
        self.send_carrier_out()

    def send_carrier_out(self):
        """发送托盘出站事件."""
        carrier_code = self.get_dv_value_with_name("carrier_code")
        if len(self.temp_save_product[carrier_code]["product_codes"]) == 4:
            product_codes_states = self.temp_save_product.pop(carrier_code)
            product_codes = product_codes_states.get("product_codes")
            self.set_dv_value_with_name("product_codes", product_codes)
            product_states = product_codes_states.get("product_states")
            self.set_dv_value_with_name("product_states", product_states)
            self.send_s6f11("carrier_out")

    def wait_eap_reply(self, *args, **kwargs):
        """等待EAP回复进站."""
        self.set_dv_value_with_name("reply_flag", True)

        self.logger.info(args, kwargs)
        time_out = 0
        while not self.get_dv_value_with_name("reply_flag"):
            time_out += 1
            self.logger.info("EAP 未回复, 等待 1 秒")
            time.sleep(1)
            if time_out == 5:
                self.logger.info("EAP 未在 5s 内回复")
                break
        self.set_dv_value_with_name("reply_flag", False)

