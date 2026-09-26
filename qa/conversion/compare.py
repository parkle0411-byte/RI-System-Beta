# 比對 A 與 B 的擷取結果；列出前幾個差異的位置
import json, sys

def diff(a, b, path="$", out=None):
    out = [] if out is None else out
    if len(out) >= 20:
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}.{k}: only in {'B' if k not in a else 'A'}")
            else:
                diff(a[k], b[k], f"{path}.{k}", out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: length A={len(a)} B={len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, f"{path}[{i}]", out)
    elif a != b:
        out.append(f"{path}: A={json.dumps(a, ensure_ascii=False)[:120]} B={json.dumps(b, ensure_ascii=False)[:120]}")
    return out

a, b = (json.loads(open(p).read().split("CAPTURE", 1)[1]) for p in sys.argv[1:3])
d = diff(a, b)
cases = len(a["perCase"])
print(f"compared {cases} cases and {len(a) - 1} screens: " + ("IDENTICAL" if not d else f"{len(d)} difference(s)"))
for line in d:
    print("  " + line)
sys.exit(1 if d else 0)
