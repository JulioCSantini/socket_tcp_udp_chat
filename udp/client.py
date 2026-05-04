import socket
import sys
import threading
import time


def _normalize_client_host(host: str) -> str:
    h = (host or "").strip()
    if h in ("0.0.0.0", "", "::"):
        return "127.0.0.1"
    return h


def _print_server_line(line: str) -> None:
    if line.startswith("OK "):
        print(f"[Servidor] Identificado como: {line[3:]}")
    elif line.startswith("ERR "):
        print(f"[Servidor] Erro: {line[4:]}")
    elif line.startswith("USERS "):
        users = line[6:].strip()
        print(f"[Usuários online] {users or '(só você na lista)'}")
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
    elif line == "PONG":
        pass
    else:
        print(line)


def connect_server(host: str, port: int) -> None:
    host = _normalize_client_host(host)
    server_addr = (host, port)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", 0))
    sock.settimeout(1.0)

    def send_line(line: str) -> None:
        sock.sendto((line + "\n").encode("utf-8"), server_addr)

    def recv_loop(stop: threading.Event) -> None:
        buf = ""
        while not stop.is_set():
            try:
                data, _src = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            buf += data.decode("utf-8", errors="replace")
            while "\n" in buf:
                ln, buf = buf.split("\n", 1)
                ln = ln.strip("\r")
                if ln:
                    _print_server_line(ln)

    print(f"UDP apontando para {host}:{port} (porta local {sock.getsockname()[1]})")

    nome = input("Seu nome de usuário (letras, números, _ . -): ").strip()
    send_line(f"IDENT {nome}")

    buf = b""
    sock.settimeout(5.0)
    while b"\n" not in buf:
        try:
            chunk, _ = sock.recvfrom(4096)
        except socket.timeout:
            print("Sem resposta do servidor (timeout). Verifique host/porta e se o servidor UDP está rodando.")
            sock.close()
            return
        buf += chunk
    sock.settimeout(1.0)

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

    pending = rest.decode("utf-8", errors="replace")

    stop = threading.Event()
    t = threading.Thread(target=recv_loop, args=(stop,), daemon=True)
    t.start()

    if pending:
        for part in pending.split("\n"):
            p = part.strip("\r")
            if p:
                _print_server_line(p)

    def heartbeat() -> None:
        while not stop.is_set():
            time.sleep(45)
            try:
                send_line("PING")
            except OSError:
                break

    hb = threading.Thread(target=heartbeat, daemon=True)
    hb.start()

    print(
        "Comandos: LIST | WHO | ROOMS | JOINROOM <sala> | PRIV <usuario> <msg> | "
        "texto = mensagem na sua sala | (PING automático mantém sessão)"
    )
    try:
        while True:
            msg = input()
            if msg is None:
                break
            send_line(msg)
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        stop.set()
        sock.close()


if __name__ == "__main__":
    HOST = "127.0.0.1"
    PORT = 8000
    if len(sys.argv) >= 2:
        HOST = sys.argv[1]
    if len(sys.argv) >= 3:
        PORT = int(sys.argv[2])
    connect_server(HOST, PORT)
