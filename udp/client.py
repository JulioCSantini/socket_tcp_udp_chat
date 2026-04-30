import socket

def connect_server(host: str, port: int):
    client_socket =  socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    nome = input('type your name: ')
    while True:
        message = input('type you message: ')
        data = f"{nome}!#{message}".encode('utf-8')

        client_socket.sendto(data, (host,port))

if __name__=='__main__':

    HOST = '10.20.25.186'
    # HOST = 'localhost'
    PORT = 8000

    connect_server(HOST,PORT)
