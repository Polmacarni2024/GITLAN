#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
version2.py

Sistema de conexion remota entre Termux y Zapia mediante Cloudflare Tunnel.

Modos:
- receptor
- conector
- diagnostico
- instalar

Objetivo aprobado:
- Cloudflare Tunnel como unico transporte.
- Sin Telegram.
- Sin expiracion automatica.
- Sin aprobacion manual.
- Control total para Zapia.
- Instalacion completa de cloudflared en Termux si falta.
- Salida visual con ANSI en terminal interactiva.
- Salida JSON limpia para automatizacion.
"""

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_NAME = "receptoryconector"
USER_AGENT = "receptoryconector/2.0"
CONFIG_DIR = Path.home() / ".receptoryconector"
BIN_DIR = CONFIG_DIR / "bin"
SESSION_FILE = CONFIG_DIR / "session.json"
LOG_FILE = CONFIG_DIR / "events.log"
LOCAL_CLOUDFLARED = BIN_DIR / "cloudflared"

INTERACTIVE = sys.stdin.isatty() and sys.stdout.isatty()
USE_COLOR = INTERACTIVE and "NO_COLOR" not in os.environ
RESET = "\033[0m" if USE_COLOR else ""
BOLD = "\033[1m" if USE_COLOR else ""
DIM = "\033[2m" if USE_COLOR else ""
RED = "\033[31m" if USE_COLOR else ""
GREEN = "\033[32m" if USE_COLOR else ""
YELLOW = "\033[33m" if USE_COLOR else ""
BLUE = "\033[34m" if USE_COLOR else ""
CYAN = "\033[36m" if USE_COLOR else ""


def color(text, code=""):
    return f"{code}{text}{RESET}" if code else str(text)


def heading(text):
    if INTERACTIVE:
        print(f"\n{color(text, BOLD)}\n")


def info(text):
    if INTERACTIVE:
        print(color(text, BLUE))


def success(text):
    if INTERACTIVE:
        print(color(text, GREEN))


def warning(text):
    if INTERACTIVE:
        print(color(text, YELLOW))


def failure(text):
    if INTERACTIVE:
        print(color(text, RED), file=sys.stderr)


def value(label, item, shade=CYAN):
    if INTERACTIVE:
        print(f"{label}: {color(item, shade)}")


def emit_json(payload, stream=None):
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=stream or sys.stdout)


def ensure_dirs():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CONFIG_DIR, 0o700)
        os.chmod(BIN_DIR, 0o700)
    except OSError:
        pass


def log_event(message):
    try:
        ensure_dirs()
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")
    except OSError:
        pass


def partial_token(token):
    token = str(token or "")
    if len(token) <= 10:
        return "***" if token else ""
    return f"{token[:6]}...{token[-4:]}"


def check_internet(timeout=8):
    for url in ("https://api.github.com", "https://one.one.one.one/cdn-cgi/trace"):
        try:
            req = urllib.request.Request(url, method="GET", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            continue
    return False


def save_session(payload):
    ensure_dirs()
    try:
        SESSION_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.chmod(SESSION_FILE, 0o600)
        return True
    except Exception as exc:
        if INTERACTIVE:
            failure(f"No se pudo guardar la sesion: {exc}")
        return False


def load_session():
    try:
        if SESSION_FILE.exists():
            data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def delete_session():
    try:
        SESSION_FILE.unlink(missing_ok=True)
    except OSError:
        pass


# cloudflared

def validate_cloudflared(path, timeout=15):
    if not path:
        return None
    path = Path(path)
    if not path.exists() or not os.access(path, os.X_OK):
        return None
    try:
        result = subprocess.run([str(path), "--version"], capture_output=True, text=True, timeout=timeout)
        output = (result.stdout or result.stderr or "").strip()
        if result.returncode == 0 and "cloudflared" in output.lower():
            return {"path": path, "version": output}
    except Exception:
        pass
    return None


def find_cloudflared():
    candidates = []
    found = shutil.which("cloudflared")
    if found:
        candidates.append(Path(found))
    candidates.append(LOCAL_CLOUDFLARED)
    for candidate in candidates:
        checked = validate_cloudflared(candidate)
        if checked:
            return checked
    return None


def architecture_asset():
    try:
        machine = os.uname().machine.lower()
    except Exception:
        machine = ""
    mapping = {
        "aarch64": "cloudflared-linux-arm64",
        "arm64": "cloudflared-linux-arm64",
        "armv7l": "cloudflared-linux-arm",
        "armv6l": "cloudflared-linux-arm",
        "arm": "cloudflared-linux-arm",
        "x86_64": "cloudflared-linux-amd64",
        "amd64": "cloudflared-linux-amd64",
        "i686": "cloudflared-linux-386",
        "i386": "cloudflared-linux-386",
        "x86": "cloudflared-linux-386",
    }
    return machine, mapping.get(machine)


def run_install_command(label, command, attempts):
    attempts.append(label)
    info(f"Intentando instalacion mediante {label}...")
    try:
        result = subprocess.run(command, check=False)
        checked = find_cloudflared()
        if checked:
            success(f"Cloudflared instalado correctamente mediante {label}.")
            return checked
        if result.returncode != 0:
            warning(f"El metodo {label} termino con codigo {result.returncode}.")
    except Exception as exc:
        warning(f"El metodo {label} no se pudo completar: {exc}")
    return None


def download_cloudflared(attempts):
    machine, asset = architecture_asset()
    attempts.append("descarga_compatible")
    if not asset:
        warning(f"No existe una descarga predefinida para la arquitectura {machine or 'desconocida'}.")
        return None
    info(f"Descargando el ejecutable correspondiente a {machine}: {asset}...")
    url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/{asset}"
    temp_path = LOCAL_CLOUDFLARED.with_suffix(".part")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=180) as response, temp_path.open("wb") as fh:
            shutil.copyfileobj(response, fh)
        temp_path.chmod(0o755)
        temp_path.replace(LOCAL_CLOUDFLARED)
        checked = validate_cloudflared(LOCAL_CLOUDFLARED)
        if checked:
            success("La descarga compatible funciona correctamente.")
            return checked
        warning("El archivo descargado no puede ejecutarse en este entorno Termux.")
    except Exception as exc:
        warning(f"La descarga compatible fallo: {exc}")
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
    return None


def compile_cloudflared(attempts):
    attempts.append("compilacion_local")
    info("Metodo final: compilacion local para Termux...")
    package_manager = shutil.which("pkg") or shutil.which("apt")
    if not package_manager:
        warning("No se encontro pkg ni apt para instalar las dependencias de compilacion.")
        return None
    try:
        deps = [package_manager, "install", "-y", "golang", "git", "make"]
        if subprocess.run(deps, check=False).returncode != 0:
            warning("No se pudieron instalar las dependencias de compilacion.")
            return None
        with tempfile.TemporaryDirectory(prefix="cloudflared-build-") as temp_dir:
            source = Path(temp_dir) / "cloudflared"
            clone = subprocess.run([
                "git", "clone", "--depth", "1",
                "https://github.com/cloudflare/cloudflared.git", str(source)
            ], check=False)
            if clone.returncode != 0:
                warning("No se pudo descargar el codigo fuente de Cloudflared.")
                return None
            env = os.environ.copy()
            env["GOOS"] = "android"
            build = subprocess.run([
                "go", "build", "-o", str(LOCAL_CLOUDFLARED), "./cmd/cloudflared"
            ], cwd=source, env=env, check=False)
            if build.returncode != 0:
                warning("La compilacion local no se completo.")
                return None
        LOCAL_CLOUDFLARED.chmod(0o755)
        checked = validate_cloudflared(LOCAL_CLOUDFLARED)
        if checked:
            success("Cloudflared fue compilado correctamente para Termux.")
            return checked
    except Exception as exc:
        warning(f"La compilacion local fallo: {exc}")
    return None


def install_cloudflared():
    ensure_dirs()
    heading("Instalacion de Cloudflared")
    attempts = []
    existing = find_cloudflared()
    if existing:
        if INTERACTIVE:
            success("Cloudflared ya esta instalado y funciona correctamente.")
            value("Ruta", str(existing["path"]))
            value("Version", existing["version"])
        return existing, attempts

    if INTERACTIVE:
        print("Cloudflared no esta disponible.")
        print("Se intentaran todos los metodos compatibles con Termux.\n")

    pkg = shutil.which("pkg")
    apt = shutil.which("apt")

    if pkg:
        checked = run_install_command("pkg", [pkg, "update", "-y"], attempts)
        if not checked:
            checked = run_install_command("pkg_install", [pkg, "install", "-y", "cloudflared"], attempts)
        if checked:
            return checked, attempts

    if apt:
        checked = run_install_command("apt_update", [apt, "update", "-y"], attempts)
        if not checked:
            checked = run_install_command("apt_install", [apt, "install", "-y", "cloudflared"], attempts)
        if checked:
            return checked, attempts

    if pkg:
        checked = run_install_command("actualizacion_repositorios", [pkg, "upgrade", "-y"], attempts)
        if not checked:
            checked = run_install_command("reintento_pkg", [pkg, "install", "-y", "cloudflared"], attempts)
        if checked:
            return checked, attempts

    checked = download_cloudflared(attempts)
    if checked:
        return checked, attempts

    checked = compile_cloudflared(attempts)
    if checked:
        return checked, attempts

    return None, attempts


def ensure_cloudflared(interactive):
    found = find_cloudflared()
    if found:
        return found
    if interactive:
        warning("Cloudflared no esta instalado o no funciona correctamente.")
        try:
            answer = input("¿Instalarlo ahora usando todos los metodos compatibles? (s/n): ").strip().lower()
        except EOFError:
            answer = ""
        if answer.startswith(("s", "y")):
            installed, _ = install_cloudflared()
            return installed
        failure("Instalacion cancelada. El receptor no puede iniciarse sin Cloudflared.")
        return None
    emit_json({
        "error": "cloudflared_no_instalado",
        "detalle": "cloudflared no esta instalado o no funciona correctamente.",
        "comando_sugerido": "python3 version2.py instalar"
    })
    return None


def start_cloudflared(path, port, timeout=90):
    command = [str(path), "tunnel", "--url", f"http://127.0.0.1:{port}"]
    log_event(f"iniciando_cloudflared puerto={port}")
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, bufsize=1)
    except Exception as exc:
        return None, None, [str(exc)]

    recent_lines = deque(maxlen=80)
    url_holder = {"url": None}
    url_event = threading.Event()

    def reader():
        try:
            for raw in process.stdout:
                line = raw.rstrip()
                recent_lines.append(line)
                if url_holder["url"] is None:
                    match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                    if match:
                        url_holder["url"] = match.group(0)
                        url_event.set()
        except Exception:
            pass

    threading.Thread(target=reader, daemon=True).start()
    started = time.monotonic()
    last_notice = 0
    while time.monotonic() - started < timeout:
        if url_event.wait(0.25):
            return process, url_holder["url"], list(recent_lines)
        if process.poll() is not None:
            break
        elapsed = int(time.monotonic() - started)
        if INTERACTIVE and elapsed >= 15 and elapsed - last_notice >= 15:
            info(f"Cloudflare todavia esta preparando el tunel. Tiempo transcurrido: {elapsed} segundos")
            last_notice = elapsed

    stop_process(process)
    return None, None, list(recent_lines)


def stop_process(process):
    if not process or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=5)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


class ReceptorState:
    def __init__(self, token, server):
        self.token = token
        self.server = server
        self.url = None
        self.active = False
        self.closing = False
        self.cloudflared_proc = None
        self.stop_event = threading.Event()
        self.start_time = time.time()


def request_shutdown(state, reason):
    if state.closing:
        return
    state.closing = True
    state.active = False
    log_event(f"cerrando reason={reason}")
    stop_process(state.cloudflared_proc)
    delete_session()
    if state.server:
        threading.Thread(target=state.server.shutdown, daemon=True).start()
    state.stop_event.set()


def monitor_cloudflared(process, state):
    process.wait()
    if not state.closing:
        log_event("cloudflared_termino_inesperadamente")
        if INTERACTIVE:
            failure("\nCloudflared termino inesperadamente. Cerrando el receptor local...")
        request_shutdown(state, "cloudflared_caido")


def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ReceptorYConector/2.0"
        protocol_version = "HTTP/1.0"

        def log_message(self, *args):
            pass

        def _send_json(self, code, payload):
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self):
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
            except ValueError:
                return None
            if length <= 0:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8", errors="replace"))
            except Exception:
                return None

        def _authenticated(self, body):
            token = self.headers.get("X-Session-Token")
            if not token and isinstance(body, dict):
                token = body.get("token")
            return bool(token) and secrets.compare_digest(str(token), state.token)

        def do_POST(self):
            if self.path != "/api":
                self._send_json(404, {"error": "ruta_no_encontrada"})
                return
            if state.closing:
                self._send_json(503, {"error": "sesion_cerrando"})
                return
            body = self._read_json()
            if body is None:
                self._send_json(400, {"error": "json_invalido"})
                return
            if not self._authenticated(body):
                log_event("token_invalido")
                if INTERACTIVE:
                    warning("Solicitud rechazada: token invalido.")
                self._send_json(401, {"error": "token_invalido"})
                return
            action = body.get("action")
            if INTERACTIVE:
                info(f"\nSolicitud recibida: {action}")
            if action == "status":
                self._send_json(200, {
                    "status": "activo", "transport": "cloudflare", "url": state.url,
                    "session_token": partial_token(state.token),
                    "uptime_seconds": int(time.time() - state.start_time),
                    "expiracion_automatica": False
                })
            elif action == "list":
                self.handle_list(body)
            elif action == "exec":
                self.handle_exec(body)
            elif action == "close":
                log_event("accion=close")
                self._send_json(200, {"status": "cerrando"})
                threading.Timer(0.35, request_shutdown, args=(state, "cierre_remoto")).start()
            else:
                self._send_json(400, {"error": "accion_desconocida"})

        def handle_list(self, body):
            path = os.path.abspath(os.path.expanduser(body.get("path") or str(Path.home())))
            if not os.path.exists(path):
                self._send_json(404, {"error": "ruta_inexistente", "path": path})
                return
            if not os.path.isdir(path):
                self._send_json(400, {"error": "no_es_directorio", "path": path})
                return
            entries = []
            try:
                with os.scandir(path) as iterator:
                    for entry in iterator:
                        item = {"name": entry.name, "path": entry.path}
                        try:
                            item["is_dir"] = entry.is_dir(follow_symlinks=False)
                            item["is_file"] = entry.is_file(follow_symlinks=False)
                            if item["is_file"]:
                                item["size"] = entry.stat(follow_symlinks=False).st_size
                        except Exception:
                            item["error"] = "no_accesible"
                        entries.append(item)
                entries.sort(key=lambda x: x.get("name", "").lower())
                self._send_json(200, {"path": path, "count": len(entries), "entries": entries})
            except PermissionError:
                self._send_json(403, {"error": "permiso_denegado", "path": path})
            except Exception as exc:
                self._send_json(500, {"error": str(exc), "path": path})

        def handle_exec(self, body):
            command = body.get("command")
            if not command:
                self._send_json(400, {"error": "comando_faltante"})
                return
            cwd = os.path.abspath(os.path.expanduser(body.get("cwd") or str(Path.home())))
            if not os.path.isdir(cwd):
                cwd = str(Path.home())
            log_event("accion=exec")
            try:
                if isinstance(command, list):
                    proc = subprocess.run(command, shell=False, cwd=cwd, capture_output=True,
                                          stdin=subprocess.DEVNULL)
                else:
                    proc = subprocess.run(str(command), shell=True, cwd=cwd, capture_output=True,
                                          stdin=subprocess.DEVNULL)
                self._send_json(200, {
                    "returncode": proc.returncode,
                    "stdout": proc.stdout.decode("utf-8", errors="replace"),
                    "stderr": proc.stderr.decode("utf-8", errors="replace")
                })
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})

    return Handler


def run_receptor():
    ensure_dirs()
    heading("Modo receptor")
    if INTERACTIVE:
        print("Transporte: Cloudflare Tunnel")
        print("Expiracion automatica: desactivada\n")
        info("Comprobando conexion a Internet...")
    if not check_internet():
        if INTERACTIVE:
            failure("No se pudo comprobar la conexion a Internet.")
            print("El receptor necesita Internet para crear el tunel Cloudflare.")
        else:
            emit_json({"error": "sin_internet"})
        return 1
    success("Conexion a Internet disponible.")
    info("\nComprobando Cloudflared...")
    cloudflared = ensure_cloudflared(INTERACTIVE)
    if not cloudflared:
        return 1
    if INTERACTIVE:
        success("Cloudflared funciona correctamente.")
        value("Ruta", str(cloudflared["path"]))
        value("Version", cloudflared["version"])
        info("\nPreparando el receptor local...")

    token = secrets.token_urlsafe(32)
    state = ReceptorState(token, None)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    state.server = server
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if INTERACTIVE:
        value("Puerto local asignado", str(port))
        success("Servidor local activo.")
        info("\nIniciando Cloudflare Tunnel...")
        print(f"Direccion local: {color(f'http://127.0.0.1:{port}', CYAN)}")
        info("Esperando la direccion publica de Cloudflare...")

    process, url, lines = start_cloudflared(cloudflared["path"], port, timeout=90)
    if not process or not url:
        request_shutdown(state, "fallo_cloudflare")
        server.server_close()
        payload = {"error": "cloudflare_no_disponible", "detalle": lines[-30:]}
        if INTERACTIVE:
            failure("No se pudo obtener una direccion publica de Cloudflare.")
            if lines:
                print("\nUltimos mensajes de Cloudflared:")
                for line in lines[-10:]:
                    print(f"  {line}")
        else:
            emit_json(payload)
        return 1

    state.cloudflared_proc = process
    state.url = url
    state.active = True
    threading.Thread(target=monitor_cloudflared, args=(process, state), daemon=True).start()
    session_payload = {
        "app": APP_NAME, "transport": "cloudflare", "url": url, "token": token,
        "created": datetime.now(timezone.utc).isoformat(), "expiracion_automatica": False
    }
    save_session(session_payload)
    log_event(f"receptor_activo url={url} token={partial_token(token)}")

    if INTERACTIVE:
        heading("Receptor activo")
        value("Transporte", "Cloudflare Tunnel")
        value("Estado", "activo", GREEN)
        value("Expiracion automatica", "desactivada")
        value("Direccion publica", url)
        value("Token", token)
        print("\nSesion guardada en:")
        print(color(str(SESSION_FILE), CYAN))
        print("\nDatos de sesion:\n")
        emit_json(session_payload)
        print("\nAcciones disponibles: status, list, exec, close")
        info("\nEsperando solicitudes...")
        print("Presiona Ctrl+C para cerrar el receptor.")
    else:
        emit_json(session_payload)

    try:
        while not state.stop_event.is_set():
            state.stop_event.wait(1)
    except KeyboardInterrupt:
        if INTERACTIVE:
            info("\nInterrupcion local recibida. Cerrando receptor...")
        request_shutdown(state, "interrupcion_manual")
    server.server_close()
    success("Receptor cerrado correctamente.")
    return 0


def normalize_url(url):
    url = str(url or "").strip()
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")


def api_request(url, token, payload, timeout=None):
    url = normalize_url(url)
    if not url:
        return None, {"error": "url_faltante"}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url + "/api", data=data, method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    req.add_header("X-Session-Token", str(token))
    req.add_header("User-Agent", USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except Exception:
            parsed = {"raw": raw}
        return exc.code, parsed
    except urllib.error.URLError as exc:
        return None, {"error": "url_error", "detalle": str(exc.reason)}
    except Exception as exc:
        return None, {"error": str(exc)}


def display_response(action, code, response):
    if not INTERACTIVE:
        emit_json({"http": code, "response": response})
        return
    if code != 200:
        failure(f"La solicitud no se completo. HTTP: {code}")
        emit_json(response)
        return
    if action == "status":
        heading("Estado del receptor")
        for label, key in (("Estado", "status"), ("Transporte", "transport"),
                           ("Direccion", "url"), ("Token", "session_token"),
                           ("Tiempo activo", "uptime_seconds"),
                           ("Expiracion automatica", "expiracion_automatica")):
            value(label, str(response.get(key, "")))
    elif action == "exec":
        heading("Resultado")
        if response.get("stdout"):
            print(response["stdout"], end="" if response["stdout"].endswith("\n") else "\n")
        if response.get("stderr"):
            print(response["stderr"], end="" if response["stderr"].endswith("\n") else "\n")
        value("Codigo de retorno", str(response.get("returncode", "")),
              GREEN if response.get("returncode") == 0 else YELLOW)
    else:
        emit_json(response)


def conector_interactive(url, token):
    while True:
        heading("Conector")
        value("Receptor", url)
        value("Token", partial_token(token))
        print("\n  1  status")
        print("  2  list")
        print("  3  exec")
        print("  4  close")
        print("  0  salir")
        try:
            choice = input("\nOpcion: ").strip()
        except EOFError:
            break
        if choice == "0":
            info("Cerrando el conector. El receptor continuara activo.")
            break
        if choice == "1":
            action, payload = "status", {"action": "status"}
        elif choice == "2":
            path = input("Ruta: ").strip() or str(Path.home())
            action, payload = "list", {"action": "list", "path": path}
        elif choice == "3":
            command = input("Comando: ").strip()
            if not command:
                continue
            action, payload = "exec", {"action": "exec", "command": command}
        elif choice == "4":
            action, payload = "close", {"action": "close"}
        else:
            failure("Opcion no valida.")
            continue
        info("Enviando solicitud...")
        code, response = api_request(url, token, payload, timeout=None if action == "exec" else 120)
        display_response(action, code, response)
        if action == "close":
            break


def run_conector(args):
    heading("Modo conector")
    session = load_session()
    url = args.url or session.get("url")
    token = args.token or session.get("token")
    interactive = sys.stdin.isatty()
    if not url or not token:
        if interactive:
            print("No se encontro una sesion local completa.")
            if not url:
                url = input("URL Cloudflare: ").strip()
            if not token:
                token = input("Token: ").strip()
        else:
            emit_json({"error": "configuracion_faltante",
                       "detalle": "Use --url y --token, o ejecute el receptor primero en el mismo usuario."})
            return 1
    if not url or not token:
        emit_json({"error": "configuracion_invalida"})
        return 1
    if not args.action:
        if interactive:
            conector_interactive(url, token)
            return 0
        emit_json({"error": "accion_faltante", "acciones": ["status", "list", "exec", "close"]})
        return 1
    payload = {"action": args.action}
    if args.action == "list":
        payload["path"] = args.path or str(Path.home())
    elif args.action == "exec":
        if not args.command:
            emit_json({"error": "comando_faltante",
                       "uso": "python3 version2.py conector exec --command 'ls -la'"})
            return 1
        payload["command"] = args.command
        if args.cwd:
            payload["cwd"] = args.cwd
    code, response = api_request(url, token, payload, timeout=None if args.action == "exec" else 120)
    display_response(args.action, code, response)
    return 0 if code == 200 else 1


def run_diagnostico():
    heading("Diagnostico")
    if INTERACTIVE:
        info("Comprobando Python, Internet, Cloudflared y la sesion local...")
    cloudflared = find_cloudflared()
    session = load_session()
    result = {
        "python": sys.version.split()[0],
        "internet": check_internet(),
        "cloudflared": str(cloudflared["path"]) if cloudflared else None,
        "cloudflared_version": cloudflared["version"] if cloudflared else None,
        "config_dir": str(CONFIG_DIR),
        "session_file": str(SESSION_FILE),
        "session_previa": bool(session.get("url")),
    }
    if INTERACTIVE:
        value("Python", result["python"], GREEN)
        value("Internet", "disponible" if result["internet"] else "no disponible",
              GREEN if result["internet"] else RED)
        value("Cloudflared", result["cloudflared"] or "no instalado",
              GREEN if cloudflared else YELLOW)
        if cloudflared:
            value("Version", result["cloudflared_version"])
        value("Sesion previa", "si" if result["session_previa"] else "no")
    else:
        emit_json(result)
    return 0 if result["internet"] and cloudflared else 1


def run_instalar():
    installed, attempts = install_cloudflared()
    payload = {
        "instalado": bool(installed),
        "ruta": str(installed["path"]) if installed else None,
        "version": installed["version"] if installed else None,
        "metodos_intentados": attempts,
    }
    if INTERACTIVE:
        if installed:
            success("\nLa instalacion esta lista para crear tuneles.")
            value("Ruta", payload["ruta"])
            value("Version", payload["version"])
        else:
            failure("\nNo se pudo instalar Cloudflared con los metodos disponibles.")
            print("Metodos intentados:")
            for method in attempts:
                print(f"  - {method}")
    else:
        emit_json(payload)
    return 0 if installed else 1


def run_menu():
    while True:
        cloudflared = find_cloudflared()
        session = load_session()
        heading("Receptor y Conector")
        value("Cloudflared", "instalado" if cloudflared else "no instalado",
              GREEN if cloudflared else YELLOW)
        value("Sesion previa", "si" if session.get("url") else "no")
        print("\n  1  Activar receptor")
        print("  2  Activar conector")
        print("  3  Diagnostico")
        print("  4  Instalar Cloudflared")
        print("  0  Salir")
        try:
            choice = input("\nOpcion: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            choice = "0"
        if choice == "1":
            run_receptor()
        elif choice == "2":
            run_conector(argparse.Namespace(action=None, url=None, token=None,
                                            path=None, command=None, cwd=None))
        elif choice == "3":
            run_diagnostico()
        elif choice == "4":
            run_instalar()
        elif choice == "0":
            info("Cerrando el programa...")
            success("Programa finalizado.")
            return 0
        else:
            failure("Opcion no valida. Escribe 1, 2, 3, 4 o 0.")


def main():
    ensure_dirs()
    parser = argparse.ArgumentParser(
        prog="version2.py",
        description="Sistema de conexion remota entre Termux y Zapia mediante Cloudflare Tunnel."
    )
    subparsers = parser.add_subparsers(dest="mode")
    subparsers.add_parser("receptor", help="Activa el receptor en Termux.")
    connector = subparsers.add_parser("conector", help="Ejecuta el conector para Zapia.")
    connector.add_argument("action", nargs="?", choices=["status", "list", "exec", "close"])
    connector.add_argument("--url")
    connector.add_argument("--token")
    connector.add_argument("--path")
    connector.add_argument("--command")
    connector.add_argument("--cwd")
    subparsers.add_parser("diagnostico", help="Verifica entorno, Internet y Cloudflared.")
    subparsers.add_parser("instalar", help="Instala Cloudflared usando todos los metodos compatibles.")
    args = parser.parse_args()
    if args.mode == "receptor":
        return run_receptor()
    if args.mode == "conector":
        return run_conector(args)
    if args.mode == "diagnostico":
        return run_diagnostico()
    if args.mode == "instalar":
        return run_instalar()
    return run_menu()


if __name__ == "__main__":
    sys.exit(main())
