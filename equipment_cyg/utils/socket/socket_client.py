import socket


class SocketClient:
    def __init__(self, host="127.0.0.1", port=22):
        self._host = host
        self._port = port
        self._client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    @property
    def host(self):
        return self._host

    @host.setter
    def host(self, host):
        self._host = host

    @property
    def port(self):
        return self._port

    @port.setter
    def port(self, port):
        self._port = port

    @property
    def client(self):
        return self._client

    @client.setter
    def client(self, client: socket):
        self._client = client

    def client_open(self):
        self.client.connect((self.host, self.port))

    def client_close(self):
        self.client.close()
        
    def client_send(self, message: str):
        data = message.encode("UTF-8")
        self.client.sendall(data)

    def client_receive(self):
        data_byte = self.client.recv(1024)
        return data_byte.decode("UTF-8")

