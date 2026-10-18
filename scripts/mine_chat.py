# -*- coding: utf-8 -*-
"""
用自己的聊天记录校准这个 skill 的语感。

用法：
    python mine_chat.py --src "D:\\你的导出目录\\JSON" --out ".\\_build"

支持两种输入：
    1. Weport / WeFlow 导出的 JSON 目录（每个会话一个 .json）
    2. 纯文本目录（每个会话一个 .txt，一行一条）

输出：
    all_own.txt          你自己的全部消息（一行一条）
    sample_random.txt    随机抽样，用来读语感
    sample_long.txt      长消息，用来看论证结构
    style_profile.json   统计指纹（句长分位、标点率、高频词、口头禅）

注意：
    - 只读，不改原文件
    - 只统计 isSend==1 的文本消息（即你自己发的）
    - 全部在本机完成，不上传
"""
import argparse
import collections
import datetime
import json
import os
import random
import re
import sys


def load_json_dir(src):
    """Weport/WeFlow 格式：每个会话一个 JSON，messages[].isSend==1 为本人。"""
    msgs = []
    files = 0
    for root, _dirs, names in os.walk(src):
        for name in names:
            if not name.lower().endswith(".json"):
                continue
            path = os.path.join(root, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            files += 1
            session = data.get("session") or {}
            peer = session.get("displayName") or session.get("remark") or name
            for m in data.get("messages") or []:
                if m.get("isSend") != 1:
                    continue
                if m.get("localType") != 1:      # 1 = 文本
                    continue
                text = (m.get("content") or "").strip()
                if not text:
                    continue
                msgs.append((m.get("createTime") or 0, text, peer))
    return msgs, files


def load_txt_dir(src):
    """纯文本格式：一行一条，全部视为本人。"""
    msgs = []
    files = 0
    for root, _dirs, names in os.walk(src):
        for name in names:
            if not name.lower().endswith(".txt"):
                continue
            files += 1
            path = os.path.join(root, name)
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for i, line in enumerate(f):
                    text = line.strip()
                    if text:
                        msgs.append((i, text, name))
    return msgs, files


def pct(sorted_lens, q):
    if not sorted_lens:
        return 0
    return sorted_lens[min(int(len(sorted_lens) * q), len(sorted_lens) - 1)]


def analyze(msgs):
    texts = [t for _, t, _ in msgs]
    lens = sorted(len(t) for t in texts)
    allt = "".join(texts)

    punct_chars = "，。？！…、；：,"
    with_punct = sum(1 for t in texts if any(c in punct_chars for c in t))

    # 高频开场 / 结尾
    openers = collections.Counter(t[:2] for t in texts if len(t) >= 2)
    enders = collections.Counter(t[-1] for t in texts if t)

    # 口头禅
    idioms = {}
    for w in ["我说实话", "说实话", "我说白了", "我只能说", "说白了", "说白了就是",
              "其实", "反正", "大概率", "基本上", "我估计", "你自己品", "行吧",
              "不是", "然后", "但是", "所以", "感觉"]:
        idioms[w] = allt.count(w)

    # 贴吧词
    slang = {}
    for w in ["典", "绷", "难绷", "逆天", "抽象", "急了", "破防", "小丑", "乐",
              "6", "666", "麻了", "寄", "润", "孝", "下头", "恶心人", "离谱"]:
        slang[w] = allt.count(w)

    # 方言
    dialect = {}
    for w in ["咋", "啥", "咱", "整", "贼", "瞅", "搁", "膈应", "磨叽", "忽悠"]:
        dialect[w] = allt.count(w)

    # 时段分布
    hours = collections.Counter()
    for ts, _, _ in msgs:
        if ts and 1_000_000_000 < ts < 4_000_000_000:
            try:
                hours[datetime.datetime.fromtimestamp(ts).hour] += 1
            except Exception:
                pass

    buckets = collections.Counter()
    for n in lens:
        if n <= 3:
            buckets["1-3"] += 1
        elif n <= 6:
            buckets["4-6"] += 1
        elif n <= 12:
            buckets["7-12"] += 1
        elif n <= 25:
            buckets["13-25"] += 1
        elif n <= 50:
            buckets["26-50"] += 1
        else:
            buckets["50+"] += 1

    return {
        "message_count": len(texts),
        "total_chars": len(allt),
        "len_mean": round(sum(lens) / len(lens), 1) if lens else 0,
        "len_median": pct(lens, 0.50),
        "len_p75": pct(lens, 0.75),
        "len_p90": pct(lens, 0.90),
        "len_p95": pct(lens, 0.95),
        "len_max": lens[-1] if lens else 0,
        "punct_message_ratio": round(100.0 * with_punct / len(texts), 1) if texts else 0,
        "buckets": dict(buckets),
        "top_openers": openers.most_common(20),
        "top_enders": enders.most_common(10),
        "idioms": idioms,
        "slang": slang,
        "dialect": dialect,
        "hours": dict(sorted(hours.items())),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="导出的聊天记录目录")
    ap.add_argument("--out", default="./_build", help="输出目录")
    ap.add_argument("--limit", type=int, default=600, help="随机抽样条数")
    ap.add_argument("--long", type=int, default=50, help="长消息最小字数")
    args = ap.parse_args()

    if not os.path.isdir(args.src):
        print("目录不存在:", args.src)
        sys.exit(1)

    has_json = any(n.lower().endswith(".json")
                   for _r, _d, ns in os.walk(args.src) for n in ns)
    msgs, files = load_json_dir(args.src) if has_json else load_txt_dir(args.src)

    if not msgs:
        print("没读到消息。检查目录结构，或确认 JSON 里有 isSend==1 的记录。")
        sys.exit(1)

    msgs.sort(key=lambda x: x[0])
    os.makedirs(args.out, exist_ok=True)

    with open(os.path.join(args.out, "all_own.txt"), "w", encoding="utf-8") as f:
        for _, t, _ in msgs:
            f.write(t.replace("\n", " / ") + "\n")

    random.seed(7)
    with open(os.path.join(args.out, "sample_random.txt"), "w", encoding="utf-8") as f:
        for _, t, _ in random.sample(msgs, min(args.limit, len(msgs))):
            f.write(t.replace("\n", " / ") + "\n")

    longs = sorted([m for m in msgs if len(m[1]) >= args.long],
                   key=lambda x: -len(x[1]))
    with open(os.path.join(args.out, "sample_long.txt"), "w", encoding="utf-8") as f:
        for _, t, _ in longs[:150]:
            f.write("[%d] %s\n" % (len(t), t.replace("\n", " / ")))

    profile = analyze(msgs)
    profile["source_files"] = files
    with open(os.path.join(args.out, "style_profile.json"), "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    print("会话文件:", files)
    print("本人文本消息:", profile["message_count"])
    print("中位句长:", profile["len_median"], "字 | p90:", profile["len_p90"], "字")
    print("带标点消息占比:", profile["punct_message_ratio"], "%")
    print("输出目录:", os.path.abspath(args.out))
    print("\n下一步：读 sample_random.txt 找感觉，读 sample_long.txt 看论证结构。")


if __name__ == "__main__":
    main()
