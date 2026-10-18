# -*- coding: utf-8 -*-
r"""
从导出的聊天记录里，自动捞出"像人"的对话切片候选。

不是直接生成例子，是给你一批候选，人工挑。
机器只能按信号打分，判断"经典不经典"还得靠人。

用法：
    python slice_dialogues.py --src "D:\你的导出目录\JSON" --out ".\_slice" --limit 120

输出：
    candidates.txt   按分数排序的对话窗口，带上下文
    candidates.json  同样的内容，结构化，方便二次筛选
"""
import argparse
import json
import os
import re
import sys

# ---------------------------------------------------------------- 信号

# 强信号：他真在"讲理/定性/怼"
STRONG = [
    "说白了", "说实话", "我说实话", "我说白了", "我只能说",
    "本质", "其实", "这不", "你以为", "你自己", "这种人", "这类人",
    "反正", "我估计", "大概率", "基本上", "不是我说",
    "凭什么", "至于", "搁这儿", "扯", "装", "恶心", "离谱",
    "逆天", "抽象", "绷", "典", "急", "孝", "人家",
]

# 弱信号：口气
WEAK = ["？", "?", "呗", "嘛", "得了", "算了", "我去", "操"]

# 具体性信号：有具体的人/物/场景
CONCRETE = ["人家", "他", "她", "我们", "我这", "我上", "昨天", "前天",
            "上个月", "去年", "今天", "早上", "晚上", "宿舍", "班里",
            "公司", "食堂", "地铁", "手机", "钱", "块"]

AI_MARK = [
    "**", "###", "|---", "首先", "其次", "综上", "以下是", "希望对",
    "建议你", "总的来说", "值得注意的是", "作为一个", "以下是针对",
    "#include", "```", "http://", "https://",
]


def is_spam(text):
    """啊啊啊啊 / 哈哈哈哈 / 666666 这种刷屏"""
    t = text.strip()
    if len(t) < 6:
        return False
    core = re.sub(r"[\s\W_]", "", t)
    if not core:
        return True
    return len(set(core)) <= 3


def looks_ai(text):
    if len(text) > 160:
        return True
    return any(m in text for m in AI_MARK)


def score_window(lines):
    """lines: [(is_me, text)]"""
    me = [t for is_me, t in lines if is_me and not is_spam(t)]
    if not me:
        return -999
    if any(looks_ai(t) for t in me):
        return -999
    if not any(not is_me for is_me, _ in lines):
        return -999

    # 至少有点内容，不能全是单字
    if max(len(t) for t in me) < 5:
        return -999
    if sum(1 for t in me if len(t) >= 4) < 2 and max(len(t) for t in me) < 12:
        return -999

    total = "".join(me)
    s = 0
    s += 2 * len(me)
    s += 3 * sum(total.count(m) for m in STRONG)
    s += 1 * sum(total.count(m) for m in WEAK)
    s += 1 * sum(1 for m in CONCRETE if m in total)
    s += 2 * sum(1 for t in me if len(t) <= 10)      # 短句连发
    s += 2 * sum(1 for t in me if t.rstrip().endswith(("？", "?")))
    if 15 <= len(total) <= 150:
        s += 4
    if len(me) >= 3:
        s += 3
    return s


def build_windows(msgs, radius=4):
    out = []
    n = len(msgs)
    for i in range(n):
        if not msgs[i][0] or is_spam(msgs[i][1]):
            continue
        lo, hi = max(0, i - radius), min(n, i + radius + 1)
        win = [(m[0], m[1]) for m in msgs[lo:hi]]
        sc = score_window(win)
        if sc > 0:
            out.append((sc, i, lo, hi, win))

    out.sort(key=lambda x: -x[0])
    kept, used_text = [], []
    for item in out:
        sc, i, lo, hi, win = item
        sig = "".join(t for m, t in win if m)[:40]
        if any(sig and sig in u for u in used_text):
            continue
        used_text.append(sig)
        kept.append(item)
    return kept


def load(src):
    sessions = []
    for root, _dirs, names in os.walk(src):
        for name in names:
            if not name.lower().endswith(".json"):
                continue
            try:
                with open(os.path.join(root, name), "r", encoding="utf-8") as f:
                    d = json.load(f)
            except Exception:
                continue
            sess = d.get("session") or {}
            peer = sess.get("displayName") or sess.get("remark") or name
            msgs = []
            for m in d.get("messages") or []:
                if m.get("localType") != 1:
                    continue
                text = (m.get("content") or "").strip()
                if not text:
                    continue
                msgs.append((m.get("isSend") == 1, text, m.get("createTime") or 0))
            if msgs:
                sessions.append((peer, name, msgs))
    return sessions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", default="./_slice")
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--radius", type=int, default=4)
    args = ap.parse_args()

    if not os.path.isdir(args.src):
        print("目录不存在:", args.src)
        sys.exit(1)

    sessions = load(args.src)
    cands = []
    for peer, fname, msgs in sessions:
        for sc, i, lo, hi, win in build_windows(msgs, args.radius):
            cands.append({
                "score": sc,
                "peer": peer,
                "file": fname,
                "ts": msgs[i][2],
                "lines": [{"me": m, "text": t} for m, t in win],
            })

    cands.sort(key=lambda x: -x["score"])
    cands = cands[: args.limit]

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "candidates.json"), "w", encoding="utf-8") as f:
        json.dump(cands, f, ensure_ascii=False, indent=2)

    with open(os.path.join(args.out, "candidates.txt"), "w", encoding="utf-8") as f:
        for k, c in enumerate(cands, 1):
            f.write("=" * 60 + "\n")
            f.write("#%d  score=%d  对方=%s\n" % (k, c["score"], c["peer"]))
            f.write("-" * 60 + "\n")
            for line in c["lines"]:
                who = "我" if line["me"] else "对方"
                f.write("%s：%s\n" % (who, line["text"]))
            f.write("\n")

    print("会话数:", len(sessions))
    print("候选:", len(cands))
    print("输出:", os.path.abspath(args.out))


if __name__ == "__main__":
    main()
