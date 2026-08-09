"""ipv4_forward_proxy.py — 强制 IPv4 的 HTTP CONNECT 隧道代理（EM 根因方案 C 验证用）。

背景：宿主机直连 EM push2 成功（requests 指纹 + IPv4 出口），但容器内经
mitmproxy 失败——mitmproxy 解析 push2 到 IPv6（240e:...）被 EM 立即断开。
本代理强制 IPv4 上游连接，仅做 TCP 双向转发（不解密 TLS），
EM 看到的是宿主机 IPv4 出口 + 客户端原始 TLS 指纹。

用法:
  python scripts/ipv4_forward_proxy.py [port]   # 默认 8081

验证（宿主机）:
  curl -x http://127.0.0.1:8081 https://push2.eastmoney.com/...
验证（容器内）:
  HTTPS_PROXY=http://host.docker.internal:8081 python -c "..."
"""
import socket
import sys
import threading


def _pipe(a: socket.socket, b: socket.socket) -> None:
    try:
        while True:
            data = a.recv(65536)
            if not data:
                break
            b.sendall(data)
    except Exception:
        pass
    finally:
        try:
            a.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            b.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass


def _handle(client: socket.socket) -> None:
    try:
        req = client.recv(4096)
        lines = req.split(b"\r\n")
        if not lines or not lines[0]:
            return
        head = lines[0].split()
        if len(head) < 2:
            return
        method, target = head[0], head[1]
        if method != b"CONNECT":
            client.sendall(b"HTTP/1.1 501 Not Implemented\r\n\r\n")
            return
        host, _, port = target.decode(errors="replace").partition(":")
        port = int(port) if port else 443
        # 强制 IPv4 上游（IPv6 出口被 EM 断连，见模块 docstring）
        try:
            ips = [i[4][0] for i in socket.getaddrinfo(host, port, socket.AF_INET)]
        except Exception:
            ips = []
        upstream = None
        for ip in ips:
            try:
                upstream = socket.create_connection((ip, port), timeout=10)
                break
            except Exception:
                continue
        if upstream is None:
            client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            return
        client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        t1 = threading.Thread(target=_pipe, args=(client, upstream), daemon=True)
        t2 = threading.Thread(target=_pipe, args=(upstream, client), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
    except Exception:
        pass
    finally:
        try:
            client.close()
        except Exception:
            pass


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port))
    srv.listen(64)
    print(f"ipv4-forward-proxy listening :{port}", flush=True)
    while True:
        client, _ = srv.accept()
        threading.Thread(target=_handle, args=(client,), daemon=True).start()


if __name__ == "__main__":
    main()
