#!/usr/bin/env python3
"""Drive a running Director Cut Studio window through its control hook, while someone watches.

Run inside the DCS container (the hook is a Unix socket there, never a network port):

    python dcs_control.py ping
    python dcs_control.py state
    python dcs_control.py highlight "OPEN PROJECT"          # outline a button or field
    python dcs_control.py open /app/dcs/<folder>/<name>.h3director.json
    python dcs_control.py work-area 0 15
    python dcs_control.py generate-prompt                    # REFRESH NOW: DCS writes its own H3 prompt
    python dcs_control.py save                               # SAVE PROJECT
    python dcs_control.py run --confirm RUN                  # RUN+QUEUE submits a render
    python dcs_control.py dismiss                            # close an open dialog

Each action outlines its widget for --highlight-ms (default 1200) before using it, and the
reply comes back at once; follow up with `state` to see the result or any dialog it opened.
"""
import argparse
import json
import os
import socket
import sys


def send(request: dict, path: str) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(15)
        client.connect(path)
        client.sendall((json.dumps(request) + "\n").encode("utf-8"))
        data = b""
        while not data.endswith(b"\n"):
            chunk = client.recv(65536)
            if not chunk:
                break
            data += chunk
    return json.loads(data.decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--socket", default=os.environ.get("DCS_CONTROL_SOCKET", "/tmp/dcs-control.sock"))
    parser.add_argument("--highlight-ms", type=int, default=1200)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ping")
    sub.add_parser("state")
    sub.add_parser("dismiss")
    sub.add_parser("generate-prompt")
    sub.add_parser("save")
    h = sub.add_parser("highlight"); h.add_argument("target")
    o = sub.add_parser("open"); o.add_argument("path")
    wa = sub.add_parser("work-area"); wa.add_argument("start", type=float); wa.add_argument("end", type=float)
    r = sub.add_parser("run"); r.add_argument("--confirm", default="")
    args = parser.parse_args()

    request = {"highlight_ms": args.highlight_ms}
    if args.cmd in ("ping", "state", "dismiss"):
        request["command"] = args.cmd
    elif args.cmd == "generate-prompt":
        request["command"] = "generate_prompt"
    elif args.cmd == "save":
        request["command"] = "save_project"
    elif args.cmd == "highlight":
        request.update(command="highlight", target=args.target)
    elif args.cmd == "open":
        request.update(command="open_project", path=args.path)
    elif args.cmd == "work-area":
        request.update(command="set_work_area", start=args.start, end=args.end)
    elif args.cmd == "run":
        request.update(command="run_queue", confirm=args.confirm)
    try:
        reply = send(request, args.socket)
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": f"cannot reach the DCS control hook at {args.socket}: {exc}"}))
        return 2
    print(json.dumps(reply, indent=2, ensure_ascii=False))
    return 0 if reply.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
