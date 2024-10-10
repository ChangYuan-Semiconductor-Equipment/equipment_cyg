"""socket 客户端."""
import socket


class SocketClient:
    """socket 客户端class."""
    def __init__(self, host="127.0.0.1", port=22):
        self._host = host
        self._port = port
        self._client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    @property
    def host(self):
        """服务端ip."""
        return self._host

    @host.setter
    def host(self, host):
        """设置连接的服务端ip."""
        self._host = host

    @property
    def port(self):
        """服务端端口号."""
        return self._port

    @port.setter
    def port(self, port):
        """设置要连接的服务端端口号."""
        self._port = port

    @property
    def client(self):
        """客户端socket实例."""
        return self._client

    @client.setter
    def client(self, client: socket):
        """设置客户端socket实例."""
        self._client = client

    def client_open(self):
        """连接服务端."""
        self.client.connect((self.host, self.port))

    def client_close(self):
        """关闭客户端连接."""
        self.client.close()

    def client_send(self, message: str):
        """客户端发送数据."""
        data = message.encode("UTF-8")
        self.client.sendall(data)

    def client_receive(self):
        """客户端接收数据."""
        data_byte = self.client.recv(1024)
        return data_byte.decode("UTF-8")
