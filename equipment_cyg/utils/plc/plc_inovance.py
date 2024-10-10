"""汇川plc modbus通讯."""
import logging
import struct
from typing import Union

from modbus_tk import defines as funcs
from modbus_tk.modbus_tcp import TcpMaster


# pylint: disable=W1203, disable=R0913, disable=R0917, disable=W0106
class PlcInovance:
    """汇川plc modbus通讯class."""
    def __init__(self, ip: str, port=502, timeout=5):
        self._ip = ip
        self._port = port
        self._timeout = timeout
        self._logger = logging.getLogger(f"{self.__module__}.{self.__class__.__name__}")
        self.master = TcpMaster(ip, port)
        self.master.set_timeout(timeout)

    @property
    def logger(self):
        """日志实例."""
        return self._logger

    @property
    def ip(self):
        """plc ip。"""
        return self._ip

    @ip.setter
    def ip(self, ip):
        """设置plc ip."""
        self._ip = ip

    @property
    def timeout(self):
        """超时时间."""
        return self._timeout

    @timeout.setter
    def timeout(self, timeout):
        """设置超时时间."""
        self._timeout = timeout

    def communication_open(self) -> bool:
        """打开和plc的通讯.

        Returns:
            bool: True代表连接成功, False代表连接失败.
        """
        try:
            self.master.open()
        except TimeoutError:
            return False
        return True

    def communication_close(self):
        """关闭和plc的通讯."""
        self.master.close()

    def execute_read(
            self, address: int, length: int = 1, data_type="int", save_log=True, real_length=20,
    ) -> Union[int, bool, str, None]:
        """根据类型读取plc数据.

        Args:
            address (int): 要读取数据的起始位.
            length (int): 要读取数据的长度.
            data_type (str): 要读取数据的数据类型.
            save_log: (bool): 是否要保存日志, 默认保存.
            real_length (int): real read value length.

        Returns:
            Union[int, bool, str]: 返回读取的数据.
        """
        save_log and self.logger.info(f"*** 准备读取{data_type} *** -> 准备读取地址 {address} 的值.")
        if data_type == "int_str":
            result = self.read_int_str(address, length, real_length)
            save_log and self.logger.info(f"*** 读取{data_type}成功 *** -> 值: {result}")
            return result
        result = self.master.execute(1, funcs.READ_HOLDING_REGISTERS, address, quantity_of_x=length)
        if data_type == "int":
            save_log and self.logger.info(f"*** 读取{data_type}成功 *** -> 值: {result[0]}")
            return result[0]
        if data_type == "bool":
            save_log and self.logger.info(f"*** 读取{data_type}成功 *** -> 值: {bool(result[0])}")
            return bool(result[0])
        if data_type == "str":
            result = "".join([chr(value) for value in result])
            save_log and self.logger.info(f"*** 读取{data_type}成功 *** -> 值: {result}")
            return result
        return None

    def execute_write(
            self, address: int, value: Union[int, bool, list], data_type: str = "int",
            save_log=True
    ) -> tuple[int, int]:
        """根据类型向plc写数据.

        Args:
            address (int): 要写入数据的起始位.
            value (Union[int, bool, list]): 要写入的数据.
            data_type (str): 要写入数据的数据类型.
            save_log (bool): 是否保存日志.

        Returns:
            tuple[int, int]: 写入成功后返回元组, int和bool返回(写入起始位, 写入值), 写入str返回(写入起始位, 写入字符串长度).
        """
        save_log and self.logger.info(f"*** 准备写入{data_type} *** -> address: {address}, value: {value}")
        if data_type in ["int", "bool"]:
            result = self.master.execute(1, funcs.WRITE_SINGLE_REGISTER, address, output_value=value)
            if result in [(address, value)]:
                save_log and self.logger.info(f"*** 写入{data_type}成功 *** -> address: {result[0]}, value: {result[1]}")
        else:
            result = self.master.execute(
                1, funcs.WRITE_MULTIPLE_REGISTERS, address, output_value=value
            )
            if result == (address, len(value)):
                save_log and self.logger.info(f"*** 写入str成功 *** -> address: {result[0]}, value_length: {result[1]}")
        return result

    def read_int(self, address: int, save_log=True) -> int:
        """读取int类型数据.

        Args:
            address (int): 要读取数据的起始位.
            save_log: (bool): 是否要保存日志, 默认保存.

        Returns:
            int: 读取的数据.
        """
        return self.execute_read(address, save_log=save_log)

    def read_bool(self, address: int, save_log=True) -> bool:
        """读取bool类型数据.

        Args:
            address (int): 要读取数据的起始位.
            save_log: (bool): 是否要保存日志, 默认保存.

        Returns:
            bool: 读取的数据.
        """
        return self.execute_read(address, data_type="bool", save_log=save_log)

    def read_str(self, address: int, length: int) -> str:
        """读取str类型数据.

        Args:
            address (int): 要读取数据的起始位.
            length (int): 要读取str数据的长度.

        Returns:
            str: 读取的数据.
        """
        return self.execute_read(address, length, data_type="str")

    def write_int(self, address: int, value: int, save_log=True) -> tuple[int, int]:
        """写入int类型数据.

        Args:
            address (int): 要写入数据的起始位.
            value (int): 要写入的数据.
            save_log (bool): 是否保存日志.

        Returns:
            tuple[int, int]: 写入成功后返回元组, (写入起始位, 写入值).
        """
        return self.execute_write(address, value, save_log=save_log)

    def write_bool(self, address: int, value: bool) -> tuple[int, int]:
        """写入bool类型数据.

        Args:
            address (int): 要写入数据的起始位.
            value (bool): 要写入的数据.

        Returns:
            tuple[int, int]: 写入成功后返回元组, (写入起始位, 写入值).
        """
        return self.execute_write(address, value, data_type="bool")

    def write_str(self, address: int, value: list) -> tuple[int, int]:
        """写入str类型数据.

        Args:
            address (int): 要写入数据的起始位.
            value (str): 要写入的数据.

        Returns:
            tuple[int, int]: 写入成功后返回元组, (写入起始位, 写入值长度).
        """
        return self.execute_write(address, value, data_type="str")

    def read_int_bit(self, address: int, bit_index) -> int:
        """读取int类型的指定bit位的值."""
        int_value = self.read_int(address, False)
        binary_str = bin(int_value)[2:][::-1]
        try:
            return int(binary_str[bit_index])
        except IndexError:
            return 0

    def write_int_bit(self, address: int, bit_index, value, save_log=True) -> tuple[int, int]:
        """向int类型具体bit写入值."""
        current_value = self.read_int(address, save_log)
        bit_mask = 1 << bit_index
        if value:
            new_value = current_value | bit_mask
        else:
            new_value = current_value & ~bit_mask
        return self.write_int(address, new_value, save_log)

    def write_int_str(self, address, value, max_length) -> tuple[int, int]:
        """向int类型写入str."""
        encoded_bytes = value.encode("UTF-8")[::-1]
        byte_length = len(encoded_bytes)
        if byte_length % 2 != 0:
            encoded_bytes = b"\x00" + encoded_bytes
        registers = []
        for i in range(0, byte_length, 2):
            word = struct.unpack(">H", encoded_bytes[i:i + 2])[0]
            registers.append(word)

        if (fix_0 := max_length // 2 - len(registers)) > 0:
            registers = [0] * fix_0 + registers
        self.logger.info(f"*** 将要写入 int_str *** -> address: {address}, value: {value}")
        result = self.write_str(address, registers[::-1])
        # self.logger.info(f"*** 确认写入 *** -> address: {address}, value: {self.read_int_str(address, max_length)}")
        return result

    def read_int_str(self, address, max_length, real_length=20) -> str:
        """读取int类型下的str."""
        if self.read_int(address) != 32:
            length = max_length // 2
            results = self.master.execute(1, funcs.READ_HOLDING_REGISTERS, address, quantity_of_x=length)
            results = results[:real_length]
            byte_data = b"".join(struct.pack(">H", reg) for reg in results[::-1])
            # noinspection PyBroadException
            try:
                value_str = byte_data.decode("UTF-8").strip("\x00")[::-1]
            except Exception:  # pylint: disable=W0718
                self.logger.warning("*** read empty data ***")
                value_str = ""
            return value_str[:max_length]
        return ""

    @staticmethod
    def get_true_bit_with_num(number) -> list:
        """根据一个整数获取具体那些bit位是True."""
        binary_str = bin(number)[2:]
        return [i for i, bit in enumerate(reversed(binary_str)) if bit == '1']
