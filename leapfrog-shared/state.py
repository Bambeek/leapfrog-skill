#!/usr/bin/env python3
"""Leapfrog progress file. Standard library only.

One small JSON file, leapfrog/state.json, so any session resumes without
re-reading the whole planning folder.

    state.py init --app "Name" --url https://app.example
    state.py show
    state.py done scout --next leapfrog-build
    state.py set slice "booking flow"
    state.py log scout 18000 "wish mining, 3 sources"
"""

import argparse
import datetime as dt
import json
import os
import sys

STEPS = ["scout", "build", "verify", "ship"]


def path_for(root):
    return os.path.join(root, "leapfrog", "state.json")


def load(root):
    p = path_for(root)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(root, state):
    p = path_for(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    state["updated"] = dt.date.today().isoformat()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def new_state(app, url):
    return {
        "app": app,
        "url": url,
        "step": "scout",
        "done": [],
        "next": "leapfrog-scout",
        "facts": {},
        "ledger": [],
    }


def summary(state):
    lines = [
        "app:  %s (%s)" % (state.get("app"), state.get("url")),
        "step: %s   done: %s" % (state.get("step"), ", ".join(state.get("done")) or "-"),
        "next: %s" % state.get("next"),
    ]
    for k, v in sorted(state.get("facts", {}).items()):
        lines.append("  %s: %s" % (k, v))
    total = sum(e.get("tokens", 0) for e in state.get("ledger", []))
    if total:
        lines.append("tokens logged: ~%d" % total)
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Leapfrog progress file")
    ap.add_argument("--root", default=".", help="project root (default .)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init")
    p.add_argument("--app", required=True)
    p.add_argument("--url", default="")
    p.add_argument("--force", action="store_true")

    sub.add_parser("show")

    p = sub.add_parser("done")
    p.add_argument("step", choices=STEPS)
    p.add_argument("--next", default=None)

    p = sub.add_parser("set")
    p.add_argument("key")
    p.add_argument("value")

    p = sub.add_parser("log")
    p.add_argument("step")
    p.add_argument("tokens", type=int)
    p.add_argument("note", nargs="?", default="")

    args = ap.parse_args(argv)
    state = load(args.root)

    if args.cmd == "init":
        if state and not args.force:
            print("state exists, use --force to replace\n" + summary(state))
            return 1
        state = new_state(args.app, args.url)
        save(args.root, state)
        print(summary(state))
        return 0

    if state is None:
        print("no leapfrog/state.json: start with leapfrog-scout")
        return 0 if args.cmd == "show" else 1

    if args.cmd == "done":
        if args.step not in state["done"]:
            state["done"].append(args.step)
        i = STEPS.index(args.step)
        state["step"] = STEPS[i + 1] if i + 1 < len(STEPS) else "complete"
        state["next"] = args.next or ("leapfrog-" + state["step"] if state["step"] != "complete" else "-")
    elif args.cmd == "set":
        state["facts"][args.key] = args.value
    elif args.cmd == "log":
        state["ledger"].append({
            "step": args.step,
            "tokens": args.tokens,
            "note": args.note,
            "date": dt.date.today().isoformat(),
        })

    if args.cmd != "show":
        save(args.root, state)
    print(summary(state))
    return 0


if __name__ == "__main__":
    sys.exit(main())
