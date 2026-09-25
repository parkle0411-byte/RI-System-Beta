"""從 Alpha grep 輸出（JSON：每行一筆 {path, line, text:"N:內容"}）還原檔案，並用 Alpha 的 SHA-256 核對是否逐位元組相同。"""
import hashlib, json, re, sys

def load(path):
    d = json.load(open(path, encoding="utf-8"))
    files = {}
    for m in d["matches"]:
        text = m["text"]
        prefix = f'{m["line"]}:'
        assert text.startswith(prefix), (m["path"], m["line"], text[:30])
        files.setdefault(m["path"], {})[m["line"]] = text[len(prefix):]
    return files

def rebuild(lines, total):
    out = [lines.get(i, "") for i in range(1, total + 1)]   # 行號的空缺 = 空行
    return "\n".join(out)

if __name__ == "__main__":
    src, dest_root = sys.argv[1], sys.argv[2]
    expect = json.loads(sys.argv[3])   # {path: [total_lines, sha256]}
    files = load(src)
    for path, (total, sha) in expect.items():
        if path not in files:
            print(f"MISSING  {path} (not in this output)"); continue
        got_max = max(files[path])
        body = rebuild(files[path], total)
        for label, data in (("no trailing newline", body), ("with trailing newline", body + "\n")):
            h = hashlib.sha256(data.encode("utf-8")).hexdigest()
            if h == sha:
                dest = f"{dest_root}/{path}"
                import os; os.makedirs(os.path.dirname(dest), exist_ok=True)
                open(dest, "w", encoding="utf-8", newline="").write(data)
                print(f"EXACT    {path}  ({label}, {total} lines, sha256 {h[:12]}…) -> {dest}")
                break
        else:
            print(f"MISMATCH {path}: max line {got_max}/{total}, sha256 {hashlib.sha256(body.encode()).hexdigest()[:12]}… vs expected {sha[:12]}…")
