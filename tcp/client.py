import socket

def connect_server(host: str, port: int):
    cliente_socket =  socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    cliente_socket.connect((host,port))
    print(f'Connecting to server')

    while True:
        message = input('type you message: ')
        cliente_socket.send(message.encode('utf-8'))


if __name__=='__main__':

    HOST = 'localhost'
    PORT = 8000

    connect_server(HOST,PORT)
