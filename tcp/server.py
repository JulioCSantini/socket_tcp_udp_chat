import logging
import re
import socket
import threading
from pathlib import Path
from typing import Dict, Optional

BUFFER_SIZE = 4096
MAX_NAME_LEN = 32
NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]{1,32}$")
ROOM_PATTERN = NAME_PATTERN
DEFAULT_ROOM = "geral"

_clients_lock = threading.Lock()
# username -> conn info (only after IDENT)
_clients_by_name: Dict[str, "ClientConn"] = {}
# all live sockets that passed IDENT
_socket_to_client: Dict[socket.socket, "ClientConn"] = {}


class ClientConn:
    __slots__ = ("sock", "addr", "username", "room", "recv_buffer", "removed")

    def __init__(self, sock: socket.socket, addr) -> None:
        self.sock = sock
        self.addr = addr
        self.username: Optional[str] = None
        self.room = DEFAULT_ROOM
        self.recv_buffer = ""
        self.removed = False


def _setup_logging(host: str, port: int) -> None:
    log_path = Path(__file__).resolve().parent / "server.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )
    logging.info("Servidor iniciando em %s:%s (log em %s)", host, port, log_path)


def _log_info(msg: str, *args: object) -> None:
    logging.info(msg, *args)


def _send_line(sock: socket.socket, line: str) -> None:
    sock.sendall((line + "\n").encode("utf-8"))


def _broadcast_line(line: str, skip: Optional[socket.socket] = None) -> None:
    data = (line + "\n").encode("utf-8")
    with _clients_lock:
        targets = [c.sock for c in _socket_to_client.values() if c.sock is not skip]
    for s in targets:
        try:
            s.sendall(data)
        except OSError:
            pass


def _broadcast_room(room: str, line: str, skip: Optional[socket.socket] = None) -> None:
    data = (line + "\n").encode("utf-8")
    with _clients_lock:
        targets = [c.sock for c in _socket_to_client.values() if c.room == room and c.sock is not skip]
    for s in targets:
        try:
            s.sendall(data)
        except OSError:
            pass


def _remove_client(conn: ClientConn) -> None:
    with _clients_lock:
        if conn.removed:
            return
        conn.removed = True
        _socket_to_client.pop(conn.sock, None)
        if conn.username:
            _clients_by_name.pop(conn.username, None)
    if conn.username:
        _log_info("Desconexão: %s (%s) usuário=%s", conn.addr, conn.sock.fileno(), conn.username)
        _broadcast_room(conn.room, f"ROOMLEAVE {conn.room} {conn.username}", skip=conn.sock)
        _broadcast_line(f"PART {conn.username}", skip=None)
    else:
        _log_info("Desconexão antes do IDENT: %s", conn.addr)
    try:
        conn.sock.close()
    except OSError:
        pass


def _handle_ident(conn: ClientConn, raw_name: str) -> bool:
    name = raw_name.strip()
    if not NAME_PATTERN.match(name):
        _send_line(conn.sock, "ERR nome inválido (use 1-32 caracteres: letras, números, _ . -)")
        _log_info("IDENT recusado de %s: nome inválido %r", conn.addr, raw_name)
        return False
    with _clients_lock:
        if name in _clients_by_name:
            _send_line(conn.sock, "ERR nome já em uso")
            _log_info("IDENT recusado de %s: nome ocupado %r", conn.addr, name)
            return False
        conn.username = name
        conn.room = DEFAULT_ROOM
        _clients_by_name[name] = conn
        _socket_to_client[conn.sock] = conn
    _send_line(conn.sock, f"OK {name}")
    _log_info("Cliente identificado: %s de %s (sala %s)", name, conn.addr, DEFAULT_ROOM)
    _broadcast_line(f"JOIN {name}", skip=conn.sock)
    _broadcast_room(DEFAULT_ROOM, f"ROOMENTER {DEFAULT_ROOM} {name}", skip=conn.sock)
    return True


def _cmd_list(conn: ClientConn) -> None:
    with _clients_lock:
        names = sorted(_clients_by_name.keys())
    _send_line(conn.sock, "USERS " + ",".join(names))
    _log_info("LIST pedido por %s", conn.username)


def _cmd_priv(conn: ClientConn, target: str, text: str) -> None:
    if not text:
        _send_line(conn.sock, "ERR uso: PRIV <usuario> <mensagem>")
        return
    with _clients_lock:
        other = _clients_by_name.get(target)
    if other is None:
        _send_line(conn.sock, f"ERR usuário não conectado: {target}")
        _log_info("PRIV falhou: %s -> %s (alvo ausente)", conn.username, target)
        return
    line_out = f"PRIV {conn.username} {text}"
    try:
        _send_line(other.sock, line_out)
        _send_line(conn.sock, f"PRIV_OK {target}")
    except OSError:
        pass
    _log_info("PRIV %s -> %s: %s", conn.username, target, text[:200])


def _broadcast_chat(conn: ClientConn, text: str) -> None:
    if not text:
        return
    line = f"CHAT {conn.room} {conn.username} {text}"
    _broadcast_room(conn.room, line, skip=conn.sock)
    _log_info("CHAT [%s] %s: %s", conn.room, conn.username, text[:200])


def _cmd_joinroom(conn: ClientConn, raw_room: str) -> None:
    r = raw_room.strip()
    if not ROOM_PATTERN.match(r):
        _send_line(conn.sock, "ERR nome de sala inválido (1-32: letras, números, _ . -)")
        return
    if r == conn.room:
        _send_line(conn.sock, f"ERR você já está na sala {r}")
        return
    old = conn.room
    conn.room = r
    _broadcast_room(old, f"ROOMLEAVE {old} {conn.username}", skip=conn.sock)
    _broadcast_room(r, f"ROOMENTER {r} {conn.username}", skip=conn.sock)
    _send_line(conn.sock, f"OKROOM {r}")
    _log_info("JOINROOM %s saiu de %s entrou em %s", conn.username, old, r)


def _cmd_rooms(conn: ClientConn) -> None:
    with _clients_lock:
        counts: Dict[str, int] = {}
        for c in _socket_to_client.values():
            counts[c.room] = counts.get(c.room, 0) + 1
    parts = [f"{name}:{counts[name]}" for name in sorted(counts.keys())]
    _send_line(conn.sock, "ROOMLIST " + ",".join(parts))
    _log_info("ROOMS pedido por %s", conn.username)


def _cmd_who(conn: ClientConn) -> None:
    with _clients_lock:
        names = sorted(c.username for c in _socket_to_client.values() if c.room == conn.room and c.username)
    _send_line(conn.sock, "ROOMUSERS " + ",".join(names))
    _log_info("WHO pedido por %s (sala %s)", conn.username, conn.room)


def _process_line(conn: ClientConn, line: str) -> Optional[str]:
    """
    Returns 'quit' to drop connection (after ERR on IDENT).
    """
    if conn.username is None:
        if line.upper().startswith("IDENT "):
            name = line[6:].strip()
            if not _handle_ident(conn, name):
                return "quit"
        else:
            _send_line(conn.sock, "ERR envie primeiro: IDENT <seu_nome>")
        return None

    if line == "LIST":
        _cmd_list(conn)
        return None

    upper = line.upper()
    if upper.startswith("JOINROOM "):
        _cmd_joinroom(conn, line[9:].strip())
        return None
    if upper == "ROOMS":
        _cmd_rooms(conn)
        return None
    if upper == "WHO":
        _cmd_who(conn)
        return None

    if upper.startswith("PRIV "):
        rest = line[5:]
        parts = rest.split(" ", 1)
        if len(parts) < 2:
            _send_line(conn.sock, "ERR uso: PRIV <usuario> <mensagem>")
            return None
        target, msg = parts[0], parts[1]
        _cmd_priv(conn, target, msg)
        return None

    _broadcast_chat(conn, line)
    return None


def _client_thread(conn: ClientConn) -> None:
    try:
        while True:
            chunk = conn.sock.recv(BUFFER_SIZE)
            if not chunk:
                break
            conn.recv_buffer += chunk.decode("utf-8", errors="replace")
            while "\n" in conn.recv_buffer:
                raw_line, conn.recv_buffer = conn.recv_buffer.split("\n", 1)
                line = raw_line.strip("\r")
                if line == "":
                    continue
                if _process_line(conn, line) == "quit":
                    _remove_client(conn)
                    return
    except OSError as e:
        _log_info("Erro de socket %s (%s): %s", conn.username or conn.addr, conn.addr, e)
    finally:
        _remove_client(conn)


def start_server(host: str, port: int) -> None:
    _setup_logging(host, port)

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(32)

    print(f"Servidor escutando em {host}:{port}")
    _log_info("Socket principal ouvindo em %s:%s", host, port)

    try:
        while True:
            client_sock, addr = server_socket.accept()
            _log_info("Nova conexão TCP de %s", addr)
            conn = ClientConn(client_sock, addr)
            t = threading.Thread(target=_client_thread, args=(conn,), daemon=True)
            t.start()
    finally:
        server_socket.close()
        _log_info("Servidor encerrado.")


if __name__ == "__main__":
    # 0.0.0.0 = aceita conexões em qualquer interface (localhost e rede local)
    HOST = "0.0.0.0"
    PORT = 8000
    start_server(HOST, PORT)
