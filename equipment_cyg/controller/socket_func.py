class SocketFunc:
    """Socket 相关函数."""

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
