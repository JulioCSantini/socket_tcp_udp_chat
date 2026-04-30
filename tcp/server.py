import socket

def  start_server(host: str, port: int):

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind((host,port))
    server_socket.listen(1)

    print(f'Server Started at {host}:{port} ')

    client_socket, addr = server_socket.accept()
    while True:

        data = client_socket.recv(1024).decode('utf-8')
        print(f'{addr}-[CLIENT]: {data}')

if __name__=='__main__':
    HOST = '10.20.25.186'
    PORT = 8000

    start_server(HOST, PORT)