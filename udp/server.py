import logging
import re
import socket
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

Addr = Tuple[str, int]

BUFFER_SIZE = 4096
SESSION_TIMEOUT_SEC = 90.0
CLEANUP_INTERVAL_SEC = 15.0
NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]{1,32}$")
ROOM_PATTERN = NAME_PATTERN
DEFAULT_ROOM = "geral"

_lock = threading.Lock()
_addr_to_user: Dict[Addr, str] = {}
_user_to_addr: Dict[str, Addr] = {}
_last_seen: Dict[Addr, float] = {}
_addr_to_room: Dict[Addr, str] = {}


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
    logging.info("UDP servidor em %s:%s (log: %s)", host, port, log_path)


def _log_info(msg: str, *args: object) -> None:
    logging.info(msg, *args)


def _send(sock: socket.socket, addr: Addr, line: str) -> None:
    try:
        sock.sendto((line + "\n").encode("utf-8"), addr)
    except OSError:
        pass


def _broadcast(sock: socket.socket, line: str, skip: Optional[Addr] = None) -> None:
    data = (line + "\n").encode("utf-8")
    with _lock:
        targets = [a for a in _addr_to_user if a != skip]
    for a in targets:
        try:
            sock.sendto(data, a)
        except OSError:
            pass


def _broadcast_room(sock: socket.socket, room: str, line: str, skip: Optional[Addr] = None) -> None:
    data = (line + "\n").encode("utf-8")
    with _lock:
        targets = [
            a
            for a in _addr_to_user
            if a != skip and _addr_to_room.get(a, DEFAULT_ROOM) == room
        ]
    for a in targets:
        try:
            sock.sendto(data, a)
        except OSError:
            pass


def _remove_addr(sock: socket.socket, addr: Addr, username: str) -> None:
    with _lock:
        room = _addr_to_room.get(addr, DEFAULT_ROOM)
        _addr_to_user.pop(addr, None)
        _last_seen.pop(addr, None)
        _addr_to_room.pop(addr, None)
        if _user_to_addr.get(username) == addr:
            _user_to_addr.pop(username, None)
    _log_info("Sessão UDP expirada ou encerrada: %s usuário=%s", addr, username)
    _broadcast_room(sock, room, f"ROOMLEAVE {room} {username}", skip=addr)
    _broadcast(sock, f"PART {username}", skip=addr)


def _cleanup_loop(sock: socket.socket, stop: threading.Event) -> None:
    while not stop.wait(CLEANUP_INTERVAL_SEC):
        now = time.monotonic()
        stale: List[Tuple[Addr, str]] = []
        with _lock:
            for addr, t in list(_last_seen.items()):
                if now - t > SESSION_TIMEOUT_SEC:
                    u = _addr_to_user.get(addr)
                    if u:
                        stale.append((addr, u))
        for addr, u in stale:
            _remove_addr(sock, addr, u)


def _touch(addr: Addr) -> None:
    _last_seen[addr] = time.monotonic()


def _handle_ident(sock: socket.socket, addr: Addr, raw_name: str) -> None:
    name = raw_name.strip()
    if not NAME_PATTERN.match(name):
        _send(sock, addr, "ERR nome inválido (use 1-32 caracteres: letras, números, _ . -)")
        _log_info("IDENT recusado de %s: nome inválido %r", addr, raw_name)
        return

    with _lock:
        old_name = _addr_to_user.get(addr)
        other = _user_to_addr.get(name)
        if other is not None and other != addr:
            _send(sock, addr, "ERR nome já em uso")
            _log_info("IDENT recusado de %s: nome ocupado %r", addr, name)
            return

        if old_name and old_name != name:
            if _user_to_addr.get(old_name) == addr:
                _user_to_addr.pop(old_name, None)

        _addr_to_user[addr] = name
        _user_to_addr[name] = addr
        _addr_to_room.setdefault(addr, DEFAULT_ROOM)
        current_room = _addr_to_room[addr]
        _touch(addr)

    if old_name and old_name != name:
        _broadcast(sock, f"PART {old_name}", skip=addr)
        _broadcast(sock, f"JOIN {name}", skip=addr)
    elif old_name is None:
        _broadcast(sock, f"JOIN {name}", skip=addr)

    _send(sock, addr, f"OK {name}")
    _log_info("Cliente UDP identificado: %s de %s (sala %s)", name, addr, current_room)
    if old_name is None:
        _broadcast_room(sock, current_room, f"ROOMENTER {current_room} {name}", skip=addr)


def _handle_list(sock: socket.socket, addr: Addr) -> None:
    with _lock:
        if addr not in _addr_to_user:
            _send(sock, addr, "ERR envie primeiro: IDENT <seu_nome>")
            return
        who = _addr_to_user[addr]
        _touch(addr)
        names = sorted(_user_to_addr.keys())
    _send(sock, addr, "USERS " + ",".join(names))
    _log_info("LIST pedido por %s (%s)", who, addr)


def _handle_priv(sock: socket.socket, addr: Addr, target: str, text: str) -> None:
    with _lock:
        sender = _addr_to_user.get(addr)
        if not sender:
            _send(sock, addr, "ERR envie primeiro: IDENT <seu_nome>")
            return
        _touch(addr)
        dest_addr = _user_to_addr.get(target)
    if not text:
        _send(sock, addr, "ERR uso: PRIV <usuario> <mensagem>")
        return
    if dest_addr is None:
        _send(sock, addr, f"ERR usuário não conectado: {target}")
        _log_info("PRIV falhou: %s -> %s (alvo ausente)", sender, target)
        return
    _send(sock, dest_addr, f"PRIV {sender} {text}")
    _send(sock, addr, f"PRIV_OK {target}")
    _log_info("PRIV %s -> %s: %s", sender, target, text[:200])


def _handle_chat(sock: socket.socket, addr: Addr, text: str) -> None:
    if not text:
        return
    with _lock:
        sender = _addr_to_user.get(addr)
        if not sender:
            _send(sock, addr, "ERR envie primeiro: IDENT <seu_nome>")
            return
        room = _addr_to_room.get(addr, DEFAULT_ROOM)
        _touch(addr)
    line = f"CHAT {room} {sender} {text}"
    _broadcast_room(sock, room, line, skip=addr)
    _log_info("CHAT [%s] %s: %s", room, sender, text[:200])


def _handle_joinroom(sock: socket.socket, addr: Addr, raw_room: str) -> None:
    r = raw_room.strip()
    if not ROOM_PATTERN.match(r):
        _send(sock, addr, "ERR nome de sala inválido (1-32: letras, números, _ . -)")
        return
    with _lock:
        sender = _addr_to_user.get(addr)
        if not sender:
            _send(sock, addr, "ERR envie primeiro: IDENT <seu_nome>")
            return
        old = _addr_to_room.get(addr, DEFAULT_ROOM)
        if r == old:
            _send(sock, addr, f"ERR você já está na sala {r}")
            return
        _addr_to_room[addr] = r
        _touch(addr)
    _broadcast_room(sock, old, f"ROOMLEAVE {old} {sender}", skip=addr)
    _broadcast_room(sock, r, f"ROOMENTER {r} {sender}", skip=addr)
    _send(sock, addr, f"OKROOM {r}")
    _log_info("JOINROOM %s saiu de %s entrou em %s", sender, old, r)


def _handle_rooms(sock: socket.socket, addr: Addr) -> None:
    with _lock:
        if addr not in _addr_to_user:
            _send(sock, addr, "ERR envie primeiro: IDENT <seu_nome>")
            return
        who = _addr_to_user[addr]
        _touch(addr)
        counts: Dict[str, int] = {}
        for a in _addr_to_user:
            rm = _addr_to_room.get(a, DEFAULT_ROOM)
            counts[rm] = counts.get(rm, 0) + 1
    parts = [f"{n}:{counts[n]}" for n in sorted(counts.keys())]
    _send(sock, addr, "ROOMLIST " + ",".join(parts))
    _log_info("ROOMS pedido por %s (%s)", who, addr)


def _handle_who(sock: socket.socket, addr: Addr) -> None:
    with _lock:
        if addr not in _addr_to_user:
            _send(sock, addr, "ERR envie primeiro: IDENT <seu_nome>")
            return
        who = _addr_to_user[addr]
        myroom = _addr_to_room.get(addr, DEFAULT_ROOM)
        _touch(addr)
        names = sorted(
            u for a, u in _addr_to_user.items() if _addr_to_room.get(a, DEFAULT_ROOM) == myroom
        )
    _send(sock, addr, "ROOMUSERS " + ",".join(names))
    _log_info("WHO pedido por %s (sala %s)", who, myroom)


def _handle_ping(sock: socket.socket, addr: Addr) -> None:
    with _lock:
        if addr not in _addr_to_user:
            _send(sock, addr, "ERR envie primeiro: IDENT <seu_nome>")
            return
        _touch(addr)
    _send(sock, addr, "PONG")
    _log_info("PING de %s (%s)", _addr_to_user.get(addr, "?"), addr)


def _process_packet(sock: socket.socket, addr: Addr, payload: str) -> None:
    line = payload.strip("\r\n")
    if not line:
        return

    upper = line.upper()
    if upper.startswith("IDENT "):
        _handle_ident(sock, addr, line[6:].strip())
        return

    if upper == "PING":
        _handle_ping(sock, addr)
        return

    with _lock:
        known = addr in _addr_to_user

    if not known:
        _send(sock, addr, "ERR envie primeiro: IDENT <seu_nome>")
        return

    if line == "LIST":
        _handle_list(sock, addr)
        return

    if upper.startswith("JOINROOM "):
        _handle_joinroom(sock, addr, line[9:].strip())
        return
    if upper == "ROOMS":
        _handle_rooms(sock, addr)
        return
    if upper == "WHO":
        _handle_who(sock, addr)
        return

    if upper.startswith("PRIV "):
        rest = line[5:]
        parts = rest.split(" ", 1)
        if len(parts) < 2:
            _send(sock, addr, "ERR uso: PRIV <usuario> <mensagem>")
            return
        _handle_priv(sock, addr, parts[0], parts[1])
        return

    _handle_chat(sock, addr, line)


def start_server(host: str, port: int) -> None:
    _setup_logging(host, port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))

    print(f"UDP servidor escutando em {host}:{port} (timeout sessão {SESSION_TIMEOUT_SEC}s)")
    _log_info("Socket UDP ouvindo em %s:%s", host, port)

    stop = threading.Event()
    cleaner = threading.Thread(target=_cleanup_loop, args=(sock, stop), daemon=True)
    cleaner.start()

    try:
        while True:
            data, addr = sock.recvfrom(BUFFER_SIZE)
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                _log_info("Pacote inválido (encoding) de %s", addr)
                continue
            if len(data) >= BUFFER_SIZE:
                _log_info("Pacote possivelmente truncado de %s", addr)
            _process_packet(sock, addr, text)
    finally:
        stop.set()
        sock.close()
        _log_info("Servidor UDP encerrado.")


if __name__ == "__main__":
    HOST = "0.0.0.0"
    PORT = 8000
    start_server(HOST, PORT)
