import socket

def  start_server(host: str, port: int):

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.bind((host,port))

    print(f'Server Started at {host}:{port} ')

    while True:
        data, addr = server_socket.recvfrom(1024)

        name = data.decode('utf-8').split('!#')[0]
        message = data.decode('utf-8').split('!#')[1]

        print(f'[{ name }] say: { message }')

if __name__=='__main__':
    HOST = '10.20.25.186'
    # HOST = 'localhost'
    PORT = 8000

    start_server(HOST, PORT)