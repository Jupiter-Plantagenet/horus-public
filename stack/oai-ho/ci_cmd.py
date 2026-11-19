#!/usr/bin/env python3
"""Send one OAI telnet-server command and print the reply (no nc/telnet needed).

  ci_cmd.py <host> <port> "<command>"     e.g. ci_cmd.py 192.168.71.150 9090 "ci fetch_du_by_ue_id"

Used for INDEPENDENT verification of the serving DU before/after a RIC-commanded
handover (the CU's own RRC answers, not the xApp), and by OAI's CI the same way.
"""
import socket
import sys
import time


def main():
    host, port, cmd = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    s = socket.create_connection((host, port), timeout=5)
    s.sendall((cmd + "\n").encode())
    s.shutdown(socket.SHUT_WR)
    buf = b""
    end = time.time() + 5
    while time.time() < end:
        try:
            chunk = s.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk
    s.close()
    sys.stdout.write(buf.decode("utf-8", "replace"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
