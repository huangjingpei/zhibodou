"""独立 Windows updater：二次验签、目录级原子切换、健康检查与自动回滚。"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import requests

from client_update.errors import UpdateError
from client_update.security import artifact_canonical, verify_ed25519


def _log_path() -> Path:
    env = os.getenv("PDK_UPDATER_LOG")
    if env:
        return Path(env)
    root = Path(os.getenv("LOCALAPPDATA") or Path.home())
    d = root / "PDK" / "updates"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"updater-{datetime.now().strftime('%Y%m%d')}.log"


_LOG_PATH = _log_path()


def log(message: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] [PDK-Updater] {message}"
    print(line, flush=True)
    try:
        with _LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def fail(message: str, code: int = 2) -> None:
    log("失败：" + message)
    raise SystemExit(code)


def sha256_file(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def report(event: str, error: str | None = None) -> None:
    decision_path = Path(os.getenv("PDK_UPDATER_DECISION_FILE") or "")
    try:
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        artifact = decision.get("artifact") or {}
        payload = {
            "checkRequestId": decision["checkRequestId"], "eventToken": decision["eventToken"],
            "artifactId": artifact.get("artifactId"), "eventType": event,
            "fromVersion": decision.get("currentVersion"), "targetVersion": decision.get("targetVersion"),
            "platform": artifact.get("platform") or "WINDOWS", "errorCategory": error,
            "clientTime": datetime.now().isoformat(timespec="seconds"),
        }
        requests.post(
            os.environ["PDK_UPDATER_API_BASE"].rstrip("/") + "/api/v1/client/updates/events",
            headers={"X-PDK-App-ID": str(decision["appId"]),
                     "X-PDK-Device-ID": os.getenv("PDK_UPDATER_DEVICE_ID", "")},
            json=payload, timeout=(3, 5),
        )
        if event == "INSTALL_SUCCEEDED":
            decision_path.unlink(missing_ok=True)
    except Exception:
        pass


def _is_process_alive(pid: int) -> bool:
    """Windows 下判断进程是否仍在运行，避免 os.kill(pid, 0) 的 WinError 6 问题。"""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259

    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    try:
        exit_code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code)):
            return exit_code.value == STILL_ACTIVE
        return False
    finally:
        kernel32.CloseHandle(h)


def wait_for_parent(pid: int, timeout: int = 90) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _is_process_alive(pid):
            return True
        time.sleep(0.5)
    return False


def _kill_process_tree(root_pid: int) -> None:
    """递归强杀 root_pid 的"其他"子孙进程，释放其占用的文件句柄。

    升级器自身、其子孙、其祖先链（含 PyInstaller onefile 的 bootloader 引导进程）、
    以及主程序 root_pid 本身都必须排除，否则会自杀或误杀正在退出的主程序。
    主程序退出后，它派生的子进程（ffmpeg / scrcpy / ADB / OBS 等）往往仍存活并
    持有 install_root 内的文件句柄，导致目录级重命名被 Windows 以 WinError 32 拒绝。
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    TH32CS_SNAPPROCESS = 0x00000002
    PROCESS_TERMINATE = 0x0001
    self_pid = os.getpid()

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    # INVALID_HANDLE_VALUE == (HANDLE)(-1)；ctypes 返回无符号大整数，用掩码判断
    if (snapshot & 0xFFFFFFFFFFFFFFFF) == 0xFFFFFFFFFFFFFFFF:
        return
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        children: dict[int, list[int]] = {}
        if kernel32.Process32First(snapshot, ctypes.byref(entry)):
            while True:
                children.setdefault(entry.th32ParentProcessID, []).append(entry.th32ProcessID)
                if not kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snapshot)

    def descendants(pid: int) -> set[int]:
        out: set[int] = set()
        queue = [pid]
        while queue:
            p = queue.pop()
            for c in children.get(p, []):
                if c not in out:
                    out.add(c)
                    queue.append(c)
        return out

    # 保护集 = 升级器自身 + 其子孙 + 其祖先链。
    # 注意两个坑：
    # 1) descendants() 不含起始 PID 本身，必须显式加 self_pid，否则会 TerminateProcess 自己；
    # 2) PyInstaller --onefile 的升级器是两个进程（bootloader 父 + Python 子），
    #    bootloader 是主程序的子进程，若不保护祖先链，bootloader 被杀后整个升级器随之死亡。
    parent_of: dict[int, int] = {}
    for parent, kids in children.items():
        for kid in kids:
            parent_of.setdefault(kid, parent)

    ancestors: set[int] = set()
    cursor = parent_of.get(self_pid)
    while cursor and cursor not in ancestors:
        ancestors.add(cursor)
        cursor = parent_of.get(cursor)

    protected = descendants(self_pid) | {self_pid} | ancestors
    # 只清理主程序的"其他"子孙（ffmpeg/scrcpy/ADB/OBS 等），主程序自身退出交给 wait_for_parent
    to_kill = sorted(descendants(root_pid) - protected)
    killed = 0
    for pid in to_kill:
        try:
            h = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
            if not h:
                continue
            kernel32.TerminateProcess(h, 1)
            kernel32.CloseHandle(h)
            killed += 1
        except Exception:
            pass
    log(f"已尝试清理父进程树：root={root_pid} 待结束={len(to_kill)} 已结束={killed}")


def _robust_replace(src: Path, dst: Path, label: str, tries: int = 6) -> None:
    """带退避重试的目录/文件原子替换，缓解杀软瞬时锁或句柄释放延迟。"""
    last: OSError | None = None
    for attempt in range(1, tries + 1):
        try:
            src.replace(dst)
            return
        except OSError as exc:
            last = exc
            log(f"{label} 第 {attempt}/{tries} 次失败：{exc}")
            if attempt < tries:
                time.sleep(0.8 * attempt)
    raise last


def _iter_files(root: Path):
    if not root.is_dir():
        return
    for path in root.rglob("*"):
        if path.is_file() or path.is_symlink():
            yield path


def _sync_tree(src: Path, dst: Path, label: str) -> int:
    """逐文件把 src 同步到 dst：覆盖同名文件、删除 dst 独有的旧文件。

    目录级重命名被外部进程（资源管理器窗口 / IDE 文件监视 / 终端 CWD 等）
    占用而无法进行时，用它就地升级 —— 这类持有者通常只锁目录句柄，
    不锁其中单个文件。单个文件被占用时抛出带具体文件名的 UpdateError，
    便于直接定位残留进程。
    """
    src_files = {p.relative_to(src).as_posix(): p for p in _iter_files(src)}
    if not src_files:
        raise UpdateError(f"{label}：新版本目录为空")
    for rel, src_path in sorted(src_files.items()):
        dest = dst.joinpath(*PurePosixPath(rel).parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src_path, dest)
        except OSError as exc:
            raise UpdateError(f"{label}：无法写入 {rel}（文件被占用，"
                              f"请关闭正在使用它的程序后重试）：{exc}") from exc
    removed = 0
    for path in list(_iter_files(dst)):
        rel = path.relative_to(dst).as_posix()
        if rel not in src_files:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass  # 旧残留文件删除失败不影响升级
    return len(src_files) + removed


def _switch_to_new_version(install_root: Path, stage: Path, backup: Path) -> str:
    """优先目录级原子替换；目录被外部进程占用时退化为逐文件就地同步。

    返回实际使用的策略："atomic" 或 "inplace"。
    """
    try:
        _robust_replace(install_root, backup, "原子替换失败（install_root.replace）", tries=3)
    except OSError as exc:
        log(f"目录被占用，无法原子替换（{exc}），改用逐文件就地同步")
        shutil.rmtree(backup, ignore_errors=True)
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copytree(install_root, backup, dirs_exist_ok=True)
        try:
            _sync_tree(stage, install_root, "就地升级")
        except UpdateError:
            # 同步中途失败（个别文件被占用）：用备份恢复已覆盖的文件后向上抛
            try:
                _sync_tree(backup, install_root, "就地升级失败回滚")
            except Exception:
                pass
            raise
        return "inplace"
    _robust_replace(stage, install_root, "切换失败（stage.replace）", tries=3)
    return "atomic"


def verify_package(args: argparse.Namespace) -> None:
    package = Path(args.package)
    if not package.is_file() or package.stat().st_size != args.file_size:
        fail("升级包不存在或大小不一致")
    digest = sha256_file(package)
    if digest.lower() != args.sha256.lower():
        fail("升级包 SHA-256 不一致")
    artifact = {
        "platform": args.platform, "arch": args.arch, "packageType": args.package_type,
        "fileSize": args.file_size, "sha256": args.sha256,
    }
    verify_ed25519(artifact_canonical(args.app_id, args.version, artifact),
                   args.signature, args.public_key, "构件")


def _safe_name(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if not normalized or pure.is_absolute() or ".." in pure.parts or any(ord(c) < 32 for c in normalized):
        fail(f"ZIP 包含不安全路径：{name}")
    return pure


def safe_extract(package: Path, target: Path, args: argparse.Namespace) -> dict[str, Any]:
    with zipfile.ZipFile(package) as archive:
        infos = archive.infolist()
        if len(infos) > 30_000:
            fail("升级包文件数量超过安全限制")
        names = {_safe_name(info.filename).as_posix() for info in infos}
        if "update-manifest.json" not in names:
            fail("升级包缺少 update-manifest.json")
        try:
            manifest = json.loads(archive.read("update-manifest.json"))
        except (KeyError, ValueError) as exc:
            fail(f"升级包清单无法解析：{exc}")
        expected = (args.app_id, args.version, args.platform, args.arch, args.entry_point)
        actual = (int(manifest.get("appId") or 0), str(manifest.get("version") or ""),
                  str(manifest.get("platform") or ""), str(manifest.get("arch") or ""),
                  str(manifest.get("entryPoint") or ""))
        if actual != expected:
            fail(f"升级包清单目标不一致：expected={expected}, actual={actual}")
        build_config = str(manifest.get("buildConfig") or "")
        allowed = {str(v) for v in (manifest.get("files") or [])} | {"update-manifest.json"}
        if not build_config or build_config not in names:
            fail("升级包没有声明有效的 buildConfig")
        if any(name not in allowed and not name.endswith("/") for name in names):
            fail("升级包包含清单之外的文件")
        try:
            embedded = json.loads(archive.read(build_config))
        except (KeyError, ValueError) as exc:
            fail(f"内嵌构建配置无法解析：{exc}")
        embedded_target = (int(embedded.get("appId") or 0), str(embedded.get("version") or ""),
                           str(embedded.get("entryPoint") or ""))
        if embedded_target != (args.app_id, args.version, args.entry_point):
            fail("内嵌构建配置与升级目标不一致")

        total = 0
        for info in infos:
            pure = _safe_name(info.filename)
            mode = info.external_attr >> 16
            if stat.S_IFMT(mode) == stat.S_IFLNK:
                fail("升级包禁止符号链接")
            total += max(0, info.file_size)
            if total > 8 * 1024 ** 3:
                fail("升级包解压体积超过 8 GiB 安全限制")
            destination = target.joinpath(*pure.parts)
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
        return manifest


def launch_entry(root: Path, entry_point: str, health_file: Path,
                 health_nonce: str) -> subprocess.Popen:
    entry = root.joinpath(*PurePosixPath(entry_point).parts)
    if not entry.is_file():
        fail("新版入口程序不存在")
    env = os.environ.copy()
    env["PDK_UPDATE_HEALTH_FILE"] = str(health_file)
    env["PDK_UPDATE_HEALTH_NONCE"] = health_nonce
    env.pop("_MEIPASS2", None)
    command = [sys.executable, str(entry)] if entry.suffix.lower() == ".py" else [str(entry)]
    return subprocess.Popen(command, cwd=root, env=env,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def healthy(path: Path, nonce: str, version: str) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("nonce") == nonce and data.get("version") == version
    except (OSError, ValueError):
        return False


def rollback(install_root: Path, backup: Path, failed_root: Path,
             entry_point: str, inplace: bool = False) -> None:
    try:
        if inplace:
            _sync_tree(backup, install_root, "回滚")
        else:
            if install_root.exists():
                _robust_replace(install_root, failed_root, "回滚：当前版本移入 failed", tries=3)
            _robust_replace(backup, install_root, "回滚：备份恢复为当前版本", tries=3)
        old_entry = install_root.joinpath(*PurePosixPath(entry_point).parts)
        if old_entry.is_file():
            subprocess.Popen([str(old_entry)], cwd=install_root,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    finally:
        shutil.rmtree(failed_root, ignore_errors=True)


def install(args: argparse.Namespace) -> int:
    log(f"开始安装：install_root={args.install_root} target={args.version} parent_pid={args.parent_pid}")
    try:
        verify_package(args)
    except UpdateError as exc:
        report("INSTALL_FAILED", "SIGNATURE_INVALID")
        log("验签/校验失败：" + str(exc))
        fail(str(exc))

    log("验签通过，清理父进程及其子进程占用后等待父进程退出")
    _kill_process_tree(args.parent_pid)
    time.sleep(0.3)  # 给 Windows 一点时间释放句柄
    if not wait_for_parent(args.parent_pid):
        report("INSTALL_FAILED", "MAIN_PROCESS_NOT_EXITED")
        fail("主程序未在 90 秒内退出，安装尚未执行")

    install_root = Path(args.install_root).resolve()
    parent = install_root.parent
    stage = parent / f".{install_root.name}.update-{args.version}-{uuid.uuid4().hex[:8]}.staging"
    backup = parent / f".{install_root.name}.backup-{int(time.time())}"
    failed_root = parent / f".{install_root.name}.failed-{uuid.uuid4().hex[:8]}"
    health_file = Path(args.health_file)
    health_file.unlink(missing_ok=True)
    try:
        stage.mkdir(parents=True)
        safe_extract(Path(args.package), stage, args)
        if not stage.joinpath(*PurePosixPath(args.entry_point).parts).is_file():
            fail("安全解压后找不到新版入口")
        log(f"解压完成，准备替换 install_root={install_root}")
        strategy = _switch_to_new_version(install_root, stage, backup)
        log(f"版本替换完成（策略={strategy}），启动新版入口做健康检查")
        process = launch_entry(install_root, args.entry_point, health_file, args.health_nonce)
        deadline = time.time() + args.health_timeout
        while time.time() < deadline and process.poll() is None:
            if healthy(health_file, args.health_nonce, args.version):
                report("INSTALL_SUCCEEDED")
                shutil.rmtree(backup, ignore_errors=True)
                health_file.unlink(missing_ok=True)
                log(f"升级到 {args.version} 成功")
                return 0
            time.sleep(0.5)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        log(f"健康检查未在 {args.health_timeout}s 内通过，准备回滚")
        rollback(install_root, backup, failed_root, args.entry_point, strategy == "inplace")
        report("INSTALL_FAILED", "HEALTH_CHECK_FAILED")
        fail("新版未通过启动健康检查，已自动恢复旧版本", 3)
    except SystemExit:
        raise
    except (Exception, UpdateError) as exc:
        import traceback
        log("安装异常：" + "".join(traceback.format_exception_only(type(exc), exc)).strip())
        report("INSTALL_FAILED", "INSTALL_EXCEPTION")
        try:
            if backup.exists() and any(backup.iterdir()):
                # 备份里有旧版本内容：无论原子替换走到哪一步，就地恢复最稳妥
                _sync_tree(backup, install_root, "异常回滚")
            elif backup.exists() and not install_root.exists():
                _robust_replace(backup, install_root, "异常回滚", tries=3)
        except Exception:
            pass
        fail(str(exc), 4)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PDK Windows 桌面客户端独立升级器")
    for name in ("package", "install-root", "version", "entry-point", "platform", "arch",
                 "package-type", "sha256", "signature", "public-key", "health-file", "health-nonce"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--app-id", type=int, required=True)
    parser.add_argument("--file-size", type=int, required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--health-timeout", type=int, default=45)
    return parser.parse_args()


if __name__ == "__main__":
    try:
        raise SystemExit(install(parse_args()))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — 兜底记录到日志，避免无控制台时静默消失
        log("未捕获异常：" + repr(exc))
        import traceback
        log(traceback.format_exc())
        raise
