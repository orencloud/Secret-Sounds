"""Check GitHub releases off the UI thread and install explicit, validated updates."""

import ast
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
import stat
from tempfile import TemporaryDirectory
from time import monotonic
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

import bpy

from .preferences import preferences, preserve_before_update

REPOSITORY = "orencloud/Secret-Sounds"
RELEASES = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
DOWNLOADS = f"https://github.com/{REPOSITORY}/releases/download/"
ASSET = "secret_sounds.zip"
MAX_BYTES = 64 * 1024 * 1024
PACKAGE = Path(__file__).resolve().parent

worker = None
pending = None
release = None
version = ()
message = ""
next_check = 0.0
restart_required = False


def fetch(url, limit):
    request = Request(url, headers={"User-Agent": "Secret-Sounds-Blender"})
    with urlopen(request, timeout=15) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("The update is too large")
    return data


def find_release(current):
    try:
        data = json.loads(fetch(RELEASES, 1024 * 1024))
    except HTTPError as error:
        if error.code == 404:
            return None
        raise
    tag = data["tag_name"]
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag) or data.get("prerelease"):
        return None
    available = tuple(map(int, tag[1:].split(".")))
    if available <= current:
        return None
    expected = f"{DOWNLOADS}{tag}/{ASSET}"
    for asset in data["assets"]:
        if asset["name"] == ASSET and asset["browser_download_url"] == expected:
            return available, expected, asset.get("digest")
    raise ValueError("The release is missing the Secret Sounds ZIP")


def unpack_update(data, expected_version):
    files = {}
    names = set()
    with ZipFile(BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > 2048 or sum(item.file_size for item in entries) > MAX_BYTES:
            raise ValueError("The update contains too much data")
        for item in entries:
            if item.is_dir():
                continue
            if not item.filename.startswith("secret_sounds/") or stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError("Unexpected file in the update")
            name = item.filename.removeprefix("secret_sounds/")
            if not re.fullmatch(r"(?:[a-zA-Z_][a-zA-Z_0-9]*\.py|README\.md|profile\.json|sounds/[^/\\:*?\"<>|\x00-\x1f]+\.(?:mp3|wav|ogg|flac))", name):
                raise ValueError("Unexpected file in the update")
            if name.casefold() in names:
                raise ValueError("Duplicate file in the update")
            names.add(name.casefold())
            files[name] = archive.read(item)
    if not {"__init__.py", "updater.py", "preferences.py", "runtime.py", "catalog.py",
            "audio.py", "theme_updates.py", "loopcut.py", "profile.json"} <= files.keys():
        raise ValueError("The update is incomplete")
    tree = ast.parse(files["__init__.py"])
    info = next((node.value for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "bl_info" for target in node.targets)), None)
    if info is None or ast.literal_eval(info)["version"] != expected_version:
        raise ValueError("The package version does not match the release")
    profile = json.loads(files["profile.json"])
    if not profile["themes"]:
        raise ValueError("The package has no default sound theme")
    for name, contents in files.items():
        if name.endswith(".py"):
            compile(contents, name, "exec")
    return files


def download(update):
    target, url, digest = update
    data = fetch(url, MAX_BYTES)
    if digest and digest != f"sha256:{sha256(data).hexdigest()}":
        raise ValueError("The download checksum did not match GitHub")
    return unpack_update(data, target)


def install(files, package, save):
    # Keep the install folder and module name stable across ZIP and legacy installs.
    previous = package.with_name(f".{package.name}.backup-{uuid4().hex}")
    with TemporaryDirectory(prefix=".secret-sounds-update-", dir=package.parent) as work:
        staged = Path(work) / "updated"
        shutil.copytree(package, staged, symlinks=True, ignore=shutil.ignore_patterns("__pycache__"))
        for relative, data in files.items():
            path = staged / relative
            if not path.resolve().is_relative_to(staged):
                raise ValueError("The install contains an external file link")
            if relative.startswith("sounds/") and path.exists():
                if path.read_bytes() != data:
                    raise ValueError("The update reuses the name of an existing sound file")
                continue
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(data)
        save()
        package.rename(previous)
        try:
            staged.rename(package)
        except OSError:
            try:
                previous.rename(package)
            except OSError as error:
                raise RuntimeError(f"Could not restore the add-on. Backup: {previous}") from error
            raise
    shutil.rmtree(previous, ignore_errors=True)


def save_themes():
    prefs = preferences()
    preserve_before_update(prefs)
    if "FINISHED" not in bpy.ops.wm.save_userpref():
        raise RuntimeError("Could not save Blender preferences before updating")


def queue(action, *args):
    global worker, pending, message
    if not bpy.app.online_access or pending or restart_required:
        return False
    if worker is None:
        worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="Secret Sounds Updates")
    pending = action, worker.submit(action, *args)
    message = "Checking for updates…" if action is find_release else "Downloading update…"
    if not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=0.1, persistent=True)
    return True


def tick():
    global pending, release, message, next_check, restart_required
    prefs = preferences()
    if pending:
        action, job = pending
        if not job.done():
            return 0.25
        pending = None
        try:
            result = job.result()
            if action is find_release:
                release = result
                message = "" if result else "You’re up to date"
            else:
                install(result, PACKAGE, save_themes)
                restart_required = True
                message = "Update installed. Restart Blender to finish."
        except (OSError, ValueError, RuntimeError, KeyError, SyntaxError, BadZipFile) as error:
            message = f"Update failed: {error}"
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "PREFERENCES":
                    area.tag_redraw()
    if not prefs or restart_required:
        return None
    if prefs.auto_check_updates and bpy.app.online_access and monotonic() >= next_check:
        next_check = monotonic() + prefs.update_interval_days * 86400
        if queue(find_release, version):
            return 0.25
    return 60.0


def start(current):
    global version, next_check, message, release, restart_required
    version, next_check, message, release, restart_required = current, 0, "", None, False
    if not bpy.app.background:
        bpy.app.timers.register(tick, first_interval=5.0, persistent=True)


def stop():
    global worker, pending
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)
    if worker:
        worker.shutdown(wait=False, cancel_futures=True)
    worker, pending = None, None


def draw_updates(layout, prefs):
    layout.prop(prefs, "show_updates", icon="TRIA_DOWN" if prefs.show_updates else "TRIA_RIGHT", emboss=False)
    if not prefs.show_updates:
        return
    box = layout.box()
    row = box.row(align=True)
    row.prop(prefs, "auto_check_updates")
    days = row.row()
    days.enabled = prefs.auto_check_updates
    days.prop(prefs, "update_interval_days")
    row = box.row(align=True)
    row.enabled = bpy.app.online_access and not (pending or restart_required)
    row.operator("secret_sounds.check_update", icon="FILE_REFRESH")
    if release and not restart_required:
        update = ".".join(map(str, release[0]))
        row.operator("secret_sounds.install_update", text=f"Install v{update}", icon="IMPORT")
    if not bpy.app.online_access:
        box.label(text="Blender’s online access is off", icon="INFO")
    elif message:
        box.label(text=message)


class CheckUpdate(bpy.types.Operator):
    bl_idname = "secret_sounds.check_update"
    bl_label = "Check for Updates"

    def execute(self, _context):
        global next_check
        if not queue(find_release, version):
            return {"CANCELLED"}
        next_check = monotonic() + preferences().update_interval_days * 86400
        return {"FINISHED"}


class InstallUpdate(bpy.types.Operator):
    bl_idname = "secret_sounds.install_update"
    bl_label = "Install Secret Sounds Update"

    def execute(self, _context):
        return {"FINISHED"} if release and queue(download, release) else {"CANCELLED"}


CLASSES = (CheckUpdate, InstallUpdate)
