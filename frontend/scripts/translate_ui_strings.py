#!/usr/bin/env python3
"""Draft the Simplified Chinese interface with Zhipu ``glm-4-flash`` (Issue #74).

Run where the API key lives (the staging VPS); it needs only the Python standard library.
It reads two English sources from ``src/locales``:

    ui-strings.json   every interface string in the code (scripts/extract-ui-strings.mjs)
    en.json           the keyed vue-i18n messages

and keeps one translation memory, ``zh-CN.dict.json`` (English -> Chinese). Only strings
missing from the memory are sent, so a re-run after a change costs only the new strings.
It then writes ``zh-CN.json``, the keyed messages, from en.json and the memory.

Nothing a user typed is ever sent: the inputs are the source code's own English.

    TRANSLATE_LLM_KEY=... python3 scripts/translate_ui_strings.py [--locales DIR] [--workers 4]

Every reply is checked before it is kept: placeholders ({0}, {name}), plural bars, the
security glossary from Issue #74 and the algorithm names that must stay English. A batch
answer that fails is retried one string at a time with a stricter prompt; a string that
still fails stays English (the interface falls back to the source) and is listed at the end.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

URL = os.environ.get("TRANSLATE_LLM_URL", "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
MODEL = os.environ.get("TRANSLATE_LLM_MODEL", "glm-4-flash")
BATCH = 15

# Issue #74's fixed glossary. (pattern in the English, wording the Chinese must contain)
GLOSSARY: list[tuple[str, str, str]] = [
    (r"\bencryption passphrase", "加密口令", "encryption passphrase = 加密口令"),
    (r"\bpassphrases?\b", "口令", "passphrase = 口令 (never 密码)"),
    (r"\bpasswords?\b", "密码", "password = 登录密码 (or 密码 when it is obviously the login one)"),
    (r"\bprivate keys?\b", "私钥", "private key = 私钥"),
    (r"\bpublic keys?\b", "公钥", "public key = 公钥"),
    # "private key file" is 私钥文件: it satisfies "private key", not this rule.
    (r"(?<!private )\bkey files?\b", "密钥文件", "key file = 密钥文件 (but private key file = 私钥文件)"),
    (r"\brecovery requests?\b", "恢复请求", "recovery request = 恢复请求"),
    (r"\brevok(e|es|ed|ing)\b", "撤销", "revoke = 撤销"),
    (r"\bintegrity checks?\b", "完整性检查", "integrity check = 完整性检查"),
    # ".ciphertext" is a file extension and stays as written.
    (r"(?<![.])\bciphertext\b", "密文", "ciphertext = 密文 (the .ciphertext file extension stays)"),
]
EXTRA_TERMS = [
    "share = 分享", "upload = 上传", "download = 下载", "file = 文件", "folder = 文件夹",
    "My Files = 我的文件", "Activity Log = 活动日志", "audit log = 审计日志",
    "account = 账户", "sign in = 登录", "settings = 设置", "unlock = 解锁", "encrypt = 加密",
    "decrypt = 解密", "tamper = 篡改", "verification code = 验证码",
    "Shuoxun Wen = 温硕勋", "Junyan Li = 李俊言", "Jason Huang = 黄建幸", "Tai Chen = 陈泰",
    "Dr. Asad Malik = Asad Malik 博士 (never transliterate)", "supervisor = 项目导师",
    "Monash University Malaysia = 马来西亚莫纳什大学", "Monash = 莫纳什",
    "School of Information Technology = 信息技术学院", "Help assistant = 帮助助手", "Education = 学习中心",
]

# Names that stay exactly as written.
KEEP = re.compile(
    r"AES-\d+-GCM|AES-GCM|AES-\d+|SHA-\d+|RSA-OAEP|RSA-\d+|RSA|Argon2id|Argon2|ChaCha20(?:-Poly1305)?|"
    r"XChaCha20(?:-Poly1305)?|HChaCha20|Poly1305|HKDF|HMAC|PBKDF2|SecureView|MCS21|FIT316[12]|"
    r"\bnonce\b|\bPEM\b|\.pem\b|\.ciphertext\b|\bJWT\b|\bTLS\b|\bHTTPS\b|\bAPI\b|-----(?:BEGIN|END) [A-Z ]+-----"
)
PLACEHOLDER = re.compile(r"\{[A-Za-z0-9_]+\}")

SYSTEM = (
    "You translate the user interface of SecureView, an end-to-end encrypted file sharing web "
    "app, from English into Simplified Chinese. Rules: translate every item of the JSON array "
    "you are given and answer with ONLY a JSON array of strings with exactly the same number "
    "of items, in the same order, no comments. Keep placeholders such as {0}, {1}, {name} "
    "exactly as written. Keep a ' | ' separator if the item has one, with the same number of "
    "parts. Keep algorithm and product names in English: AES-256-GCM, SHA-256, RSA-OAEP, "
    "Argon2id, ChaCha20, nonce, SecureView, PEM, .pem, file names, URLs, email addresses and "
    "numbers. An item may be a fragment of a sentence (text around a link or a bold word): "
    "translate it as a fragment and keep its leading or trailing punctuation. An item with "
    "line breaks is Markdown: keep every line break, list marker (-, •, 1.), table bar (|) and "
    "**bold** marker, and translate the words inside them. Use a concise, "
    "friendly product tone and address the reader as 你. Inside Chinese text use full-width "
    "punctuation (，。：；？！（）), never a half-width '. ' or ', ' between Chinese words. Keep "
    "PEM lines such as -----BEGIN PUBLIC KEY----- unchanged. Use these exact terms:\n- "
    + "\n- ".join(g[2] for g in GLOSSARY) + "\n- " + "\n- ".join(EXTRA_TERMS)
)


def faithful(source: str, reply: str) -> str | None:
    """Why a reply is not acceptable, or None when it is."""
    if not isinstance(reply, str) or not reply.strip():
        return "empty"
    if not re.search(r"[一-鿿]", reply) and re.search(r"[A-Za-z]{3,}", source):
        # Untranslated. Fine only for a bare name ("SecureView", "AES-256-GCM").
        if KEEP.sub("", source).strip(" .:-·") and not re.fullmatch(r"[A-Z0-9 .:+\-/·()]+", source):
            return "not translated"
    if sorted(PLACEHOLDER.findall(source)) != sorted(PLACEHOLDER.findall(reply)):
        return "placeholders"
    if source.count("|") != reply.count("|"):
        return "plural bars"
    if source.count("\n") != reply.count("\n"):
        return "line breaks"
    if re.search(r"[{}@$]", PLACEHOLDER.sub("", reply)) and not re.search(r"[{}@$]", PLACEHOLDER.sub("", source)):
        return "special characters"
    lower = source.lower()
    for pattern, chinese, _ in GLOSSARY:
        if re.search(pattern, lower) and chinese not in reply:
            # "passphrase" inside "encryption passphrase" is satisfied by 加密口令.
            return f"glossary {chinese}"
    if "passphrase" not in lower and "口令" in reply:
        return "口令 for a password"
    for name in set(KEEP.findall(source)):
        if name not in reply:
            return f"keep {name}"
    if len(reply) > 3 * len(source) + 40:
        return "too long"
    return None


class Client:
    def __init__(self, key: str) -> None:
        self.key = key
        self.lock = threading.Lock()
        self.requests = 0

    def chat(self, user: str, system: str = SYSTEM) -> str:
        body = json.dumps({
            "model": MODEL,
            "temperature": 0.1,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }).encode()
        delay = 5.0
        for attempt in range(6):
            with self.lock:
                self.requests += 1
            request = urllib.request.Request(
                URL + "/chat/completions", data=body,
                headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    return json.load(response)["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    sys.exit(f"the key was refused ({exc.code})")
                if exc.code == 400:
                    raise RuntimeError(f"400: {exc.read()[:200]!r}") from exc
            except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError) as exc:
                print(f"  attempt {attempt + 1}: {exc}", flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 120)
        raise RuntimeError("no answer after retries")


def parse_array(text: str) -> list | None:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < start:
        return None
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, list) else None


def translate_batch(client: Client, batch: list[str]) -> dict[str, str]:
    done: dict[str, str] = {}
    try:
        reply = parse_array(client.chat(json.dumps(batch, ensure_ascii=False)))
    except RuntimeError as exc:
        print(f"  batch failed: {exc}", flush=True)
        reply = None
    retry = []
    if reply is not None and len(reply) == len(batch):
        for source, out in zip(batch, reply):
            if faithful(source, out) is None:
                done[source] = out.strip()
            else:
                retry.append(source)
    else:
        retry = list(batch)
    for source in retry:
        strict = (
            SYSTEM + "\nThe array has ONE item. Earlier answers broke a rule: keep every "
            "placeholder and English name, and use the glossary wording exactly."
        )
        try:
            out = parse_array(client.chat(json.dumps([source], ensure_ascii=False), strict))
        except RuntimeError as exc:
            print(f"  single failed: {exc}", flush=True)
            continue
        if out and len(out) == 1 and faithful(source, out[0]) is None:
            done[source] = out[0].strip()
        else:
            reason = faithful(source, out[0]) if out and len(out) == 1 else "shape"
            print(f"  kept English ({reason}): {source[:80]!r}", flush=True)
    return done


def leaves(tree: dict, prefix: str = ""):
    for key, value in tree.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            yield from leaves(value, path)
        else:
            yield path, value


def build_keyed(en: dict, memory: dict[str, str]) -> dict:
    out: dict = {}
    for key, value in en.items():
        if isinstance(value, dict):
            out[key] = build_keyed(value, memory)
        elif value in memory:
            out[key] = memory[value]
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--locales", default=str(Path(__file__).resolve().parent.parent / "src" / "locales"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0, help="translate at most N new strings (a trial run)")
    args = parser.parse_args()

    locales = Path(args.locales)
    strings = json.loads((locales / "ui-strings.json").read_text())
    # Strings the extractor cannot recognise ("14 rounds"), listed by hand.
    extra = locales / "ui-strings.extra.json"
    if extra.exists():
        strings += json.loads(extra.read_text())
    en = json.loads((locales / "en.json").read_text())
    memory_path = locales / "zh-CN.dict.json"
    memory: dict[str, str] = json.loads(memory_path.read_text()) if memory_path.exists() else {}

    sources = sorted(set(strings) | {v for _, v in leaves(en) if isinstance(v, str)})
    pending = [s for s in sources if s not in memory]
    if args.limit:
        pending = pending[: args.limit]
    print(f"{len(sources)} strings, {len(memory)} in memory, {len(pending)} to translate", flush=True)

    key = os.environ.get("TRANSLATE_LLM_KEY", "").strip()
    if pending and not key:
        sys.exit("TRANSLATE_LLM_KEY is not set")
    client = Client(key)
    # Up to BATCH strings, or fewer when they are long (whole Markdown articles).
    batches: list[list[str]] = []
    for source in pending:
        if batches and len(batches[-1]) < BATCH and sum(map(len, batches[-1])) + len(source) <= 3000:
            batches[-1].append(source)
        else:
            batches.append([source])
    save_lock = threading.Lock()
    finished = 0

    def save() -> None:
        current = {s: memory[s] for s in sorted(memory) if s in set(sources)}
        memory_path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n")

    def run(batch: list[str]) -> None:
        nonlocal finished
        result = translate_batch(client, batch)
        with save_lock:
            memory.update(result)
            finished += 1
            if finished % 10 == 0 or finished == len(batches):
                save()
                print(f"{finished}/{len(batches)} batches, {len(memory)} in memory, "
                      f"{client.requests} requests", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run, batches))

    save()
    keyed = build_keyed(en, memory)
    (locales / "zh-CN.json").write_text(json.dumps(keyed, ensure_ascii=False, indent=2) + "\n")
    missing = [s for s in sources if s not in memory]
    print(f"done: {len(sources) - len(missing)}/{len(sources)} translated, {len(missing)} still English")
    for s in missing:
        print(f"  untranslated: {s[:100]!r}")


if __name__ == "__main__":
    main()
