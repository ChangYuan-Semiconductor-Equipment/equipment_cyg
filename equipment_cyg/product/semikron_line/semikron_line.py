from mysql_api.mysql_database import MySQLDatabase

from equipment_cyg.controller.host_controller import HostController


class SemikronLine(HostController):
    """SemikronLine class."""

    def __init__(self):
        super().__init__()

        self.mysql = MySQLDatabase(
            self.get_config_value("mysql", "user_name"),
            self.get_config_value("mysql", "password")
        )

    def _on_event_collection_event_received(self, data):
        """接收到设备发来的事件进行处理."""
        peer = data.get("peer")
        equipment_ip = peer.settings.address
        equipment_port = peer.settings.port
        self.logger.info("收到设备发来的事件: %s %s", equipment_ip, equipment_port)

        ce_id = data.get("ceid").get()
        self.logger.info("事件id: %s", ce_id)
        values = data.get("values")
        self.logger.info("事件报告的值: %s", values)

