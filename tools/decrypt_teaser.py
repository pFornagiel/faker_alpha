"""Decrypt the two encrypted files published on the NASK teaser page
(https://science.nask.pl/hacknation) for the "Kolekcjoner Fejków" challenge.

Puzzle solution (found by analysing the public teaser page):
  * scam_links.enc  - page cookies say: `openssl enc -d -aes-256-cbc -pbkdf2 -a ... -pass pass:<KLUCZ_Z_FILMU>`
                      (pbkdf2-sha256, 10000 iter). The key is motion-only text in media/footer.mp4: "93JNG".
  * ___BACKUP.zip   - AES zip linked from /hacknation/lusterko/. Pigpen cipher in media/_haslo.png decoded
                      with the vertically mirrored key media/czekoladka.png -> "WSTAWAJ SAMURAJU".

Run by the user (decision to decrypt is theirs):
    .venv/bin/python tools/decrypt_teaser.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENC_DIR = ROOT / "data" / "organizer" / "encrypted"
OUT_DIR = ROOT / "data" / "organizer"

VIDEO_KEY = "93jng"  # the video shows 93JNG, but only the lowercase form decrypts
PIGPEN = "WSTAWAJ SAMURAJU"
ZIP_CANDIDATES = [PIGPEN, PIGPEN.replace(" ", ""), PIGPEN.lower(), PIGPEN.lower().replace(" ", ""),
                  PIGPEN.title(), PIGPEN.title().replace(" ", ""), PIGPEN.replace(" ", "_"),
                  PIGPEN.lower().replace(" ", "_"), PIGPEN.capitalize(), VIDEO_KEY]


def decrypt_enc() -> None:
    src, dst = ENC_DIR / "scam_links.enc", OUT_DIR / "scam_links.txt"
    res = subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "10000", "-md", "sha256",
                          "-a", "-in", str(src), "-pass", f"pass:{VIDEO_KEY}"], capture_output=True)
    if res.returncode != 0 or not res.stdout.isascii():
        print("[enc] decryption with video key failed:", res.stderr.decode()[:200])
        return
    dst.write_bytes(res.stdout)
    print(f"[enc] OK -> {dst} ({len(res.stdout)} bytes)")
    print("[enc] NOTE: treat the links inside as live scam URLs - do not open them in a normal browser.")


def fix_name(info) -> str:
    name = info.filename
    if not (info.flag_bits & 0x800):
        try:
            name = name.encode("cp437").decode("utf-8")
        except UnicodeError:
            pass
    return name


def decrypt_zip() -> None:
    try:
        import pyzipper
    except ImportError:
        sys.exit("pip install pyzipper first")
    src = ENC_DIR / "___BACKUP.zip"
    out = (OUT_DIR / "backup").resolve()
    zf = pyzipper.AESZipFile(src)
    probe = next(i for i in zf.infolist() if not i.filename.endswith("/"))
    pwd = None
    for cand in ZIP_CANDIDATES:
        try:
            zf.read(probe, pwd=cand.encode())
            pwd = cand
            break
        except (RuntimeError, ValueError, pyzipper.BadZipFile):
            continue
    if pwd is None:
        print("[zip] none of the candidate passwords worked:", ZIP_CANDIDATES)
        return
    print(f"[zip] password = {pwd!r}; extracting to {out}")
    n = 0
    for info in zf.infolist():
        name = fix_name(info)
        target = (out / name).resolve()
        if not str(target).startswith(str(out)):
            continue  # zip-slip guard
        if name.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(zf.read(info, pwd=pwd.encode()))
        n += 1
    print(f"[zip] extracted {n} files")


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    decrypt_enc()
    decrypt_zip()
