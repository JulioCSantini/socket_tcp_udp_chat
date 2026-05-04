import socket
import sys
import threading


def _print_server_line(line: str) -> None:
    if line.startswith("OK "):
        print(f"[Servidor] Identificado como: {line[3:]}")
    elif line.startswith("ERR "):
        print(f"[Servidor] Erro: {line[4:]}")
    elif line.startswith("USERS "):
        users = line[6:].strip()
        print(f"[Usuários online] {users or '(nenhum além de você)'}")
    elif line.startswith("JOIN "):
        print(f"*** Entrou: {line[5:]}")
    elif line.startswith("PART "):
        print(f"*** Saiu: {line[5:]}")
    elif line.startswith("CHAT "):
        rest = line[5:]
        parts = rest.split(" ", 2)
        if len(parts) >= 3:
            room, who, msg = parts[0], parts[1], parts[2]
            print(f"[{room}] {who}: {msg}")
        elif len(parts) >= 2:
            who, msg = parts[0], parts[1]
            print(f"{who}: {msg}")
        else:
            print(line)
    elif line.startswith("ROOMENTER "):
        rest = line[10:].split(" ", 1)
        if len(rest) >= 2:
            print(f"*** [{rest[0]}] entrou: {rest[1]}")
        else:
            print(line)
    elif line.startswith("ROOMLEAVE "):
        rest = line[10:].split(" ", 1)
        if len(rest) >= 2:
            print(f"*** [{rest[0]}] saiu: {rest[1]}")
        else:
            print(line)
    elif line.startswith("OKROOM "):
        print(f"[Sala atual] {line[7:]}")
    elif line.startswith("ROOMLIST "):
        print(f"[Salas] {line[9:]}")
    elif line.startswith("ROOMUSERS "):
        u = line[10:].strip()
        print(f"[Nesta sala] {u or '(só você)'}")
    elif line.startswith("PRIV "):
        rest = line[5:]
        sp = rest.find(" ")
        if sp != -1:
            who, msg = rest[:sp], rest[sp + 1 :]
            print(f"[privado de {who}] {msg}")
        else:
            print(line)
    elif line.startswith("PRIV_OK "):
        print(f"[Mensagem privada enviada para {line[8:]}]")
    else:
        print(line)


def connect_server(host: str, port: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((host, port))
    except ConnectionRefusedError:
        sock.close()
        print(
            f"Não foi possível conectar em {host}:{port}.\n"
            "Inicie o servidor antes (na pasta tcp): python server.py\n"
            "Use a mesma porta; o servidor escuta em 0.0.0.0 e o cliente em 127.0.0.1 por padrão."
        )
        return
    print(f"Conectado a {host}:{port}")

    nome = input("Seu nome de usuário (letras, números, _ . -): ").strip()
    sock.sendall(f"IDENT {nome}\n".encode("utf-8"))

    buf = b""
    while b"\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            print("Servidor fechou antes da identificação.")
            sock.close()
            return
        buf += chunk
    first_line, rest = buf.split(b"\n", 1)
    line = first_line.decode("utf-8", errors="replace").strip("\r")

    if line.startswith("ERR"):
        print(f"[Servidor] {line}")
        sock.close()
        return

    _print_server_line(line)
    if not line.startswith("OK"):
        print("Resposta inesperada; encerrando.")
        sock.close()
        return

    if rest:
        leftover = rest.decode("utf-8", errors="replace")
        sock_buffer = leftover
    else:
        sock_buffer = ""

    def recv_with_prefixed_buffer() -> None:
        nonlocal sock_buffer
        try:
            while True:
                if "\n" in sock_buffer:
                    ln, sock_buffer = sock_buffer.split("\n", 1)
                    ln = ln.strip("\r")
                    if ln:
                        _print_server_line(ln)
                    continue
                chunk = sock.recv(4096)
                if not chunk:
                    print("\n[Conexão encerrada.]")
                    break
                sock_buffer += chunk.decode("utf-8", errors="replace")
        except OSError as e:
            print(f"\n[Erro ao receber: {e}]")

    t = threading.Thread(target=recv_with_prefixed_buffer, daemon=True)
    t.start()

    print(
        "Comandos: LIST | WHO | ROOMS | JOINROOM <sala> | PRIV <usuario> <msg> | "
        "texto = mensagem na sua sala"
    )
    try:
        while True:
            msg = input()
            if msg is None:
                break
            sock.sendall((msg + "\n").encode("utf-8"))
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()


if __name__ == "__main__":
    HOST = "127.0.0.1"
    PORT = 8000
    if len(sys.argv) >= 2:
        HOST = sys.argv[1]
    if len(sys.argv) >= 3:
        PORT = int(sys.argv[2])
    connect_server(HOST, PORT)
