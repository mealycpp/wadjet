#!/usr/bin/env python3
"""
Software model: what reaches an accelerator's registers when approved
jobs are mixed or cut short, under four release rules.

The same cipher (Ascon-AEAD128, NIST SP 800-232), the same job format
(12 register writes of 8 bytes each, START last) and the same approved
jobs are used for every rule. Only the rule for releasing writes differs:

  R1  check each write: tag only
  R2  check each write: tag and a forward-only counter
  R3  check each write: tag and a consecutive counter
  R4  whole job: tag over all 12 writes, sequence number used once,
      nothing released before both checks pass (Algorithm 1 of the paper)

Two attempts by the software that carries the messages:

  MIX        first k writes of approved job X, then the remaining
             writes of approved job Y (every split point k)
  CUT SHORT  approved job X runs in full; then the first k writes of
             approved job Y arrive, and nothing more (every split point k)

This is a model of release rules. It is not an implementation of any
published system.

Usage:  python3 mix_model.py [pairs] [seed] [format]
        default: 1000 pairs, seed 2026, format gemm12
        formats: gemm12 (the paper's 12-write job), conv7 (7 writes),
                 max32 (32 writes, the largest job the gate's buffers hold)
Needs ascon.py (reference implementation, https://github.com/meichlseder/pyascon)
in the same folder.
"""
import os
import random
import struct
import sys

import ascon

VAR = "Ascon-AEAD128"
FORMATS = {
    "gemm12": [0x10, 0x14, 0x1C, 0x20, 0x28, 0x2C, 0x34, 0x3C, 0x44, 0x04, 0x08, 0x00],
    "conv7": [0x10, 0x14, 0x18, 0x1C, 0x20, 0x28, 0x00],
    "max32": [0x10 + 8 * i for i in range(31)] + [0x00],
}
FORMAT = sys.argv[3] if len(sys.argv) > 3 else "gemm12"
REGS = FORMATS[FORMAT]
START_ADDR = 0x00
N_REC = len(REGS)


def make_job(rng):
    """One approved job: argument writes, then START last."""
    if FORMAT == "gemm12":
        vals = [rng.getrandbits(32) for _ in range(6)]            # addresses
        vals += [rng.randrange(1, 1 << 16) for _ in range(3)]     # M, N, K
        vals += [1, 1, 1]                                         # control, control, START
    else:
        vals = [rng.getrandbits(32) for _ in range(N_REC - 1)] + [1]
    return [(a, v) for a, v in zip(REGS, vals)]


def pack(rec):
    return struct.pack(">II", rec[0], rec[1])


def unpack(b):
    return struct.unpack(">II", b)


class Authority:
    """Holds the key. Software never sees it."""

    def __init__(self, key, epoch):
        self.key, self.epoch = key, epoch
        self.msg_counter = 0
        self.job_seq = 0

    def seal_each_write(self, job):
        out = []
        for rec in job:
            self.msg_counter += 1
            c = struct.pack(">Q", self.msg_counter)
            ct = ascon.ascon_encrypt(self.key, self.epoch + c, c, pack(rec), VAR)
            out.append((self.msg_counter, ct))
        return out

    def seal_whole_job(self, job):
        self.job_seq += 1
        s = struct.pack(">Q", self.job_seq)
        ct = ascon.ascon_encrypt(self.key, self.epoch + s, s,
                                 b"".join(pack(r) for r in job), VAR)
        return self.job_seq, ct[:-16], ct[-16:]


class Accelerator:
    """Register file. Records the configuration at the moment START is written."""

    def __init__(self):
        self.reg = {}
        self.writes = 0
        self.started_with = None

    def write(self, addr, val):
        self.writes += 1
        if addr == START_ADDR and val & 1:
            self.started_with = dict(self.reg)
        else:
            self.reg[addr] = val


def config_of(job):
    return {a: v for a, v in job if a != START_ADDR}


_checked = {}


def open_message(key, epoch, counter, ct):
    k = (key, epoch, counter, ct)
    if k not in _checked:
        c = struct.pack(">Q", counter)
        _checked[k] = ascon.ascon_decrypt(key, epoch + c, c, ct, VAR)
    return _checked[k]


class PerWriteReceiver:
    """Rules R1 to R3: every message is checked when it arrives and passed on."""

    def __init__(self, key, epoch, rule, acc):
        self.key, self.epoch, self.rule, self.acc = key, epoch, rule, acc
        self.last = 0

    def deliver(self, counter, ct):
        pt = open_message(self.key, self.epoch, counter, ct)
        if pt is None:
            return False
        if self.rule == "R2" and not counter > self.last:
            return False
        if self.rule == "R3" and counter != self.last + 1:
            return False
        self.last = counter
        self.acc.write(*unpack(pt))
        return True


class WholeJobReceiver:
    """Rule R4: quarantine, tag check, sequence check, mark used, then dispatch."""

    def __init__(self, key, epoch, acc):
        self.key, self.epoch, self.acc = key, epoch, acc
        self.last_seq = 0

    def submit(self, seq_nonce, seq_ad, body, tag):
        s = struct.pack(">Q", seq_ad)
        n = self.epoch + struct.pack(">Q", seq_nonce)
        if len(body) == 0 or len(body) % 8:
            return False
        quarantine = ascon.ascon_decrypt(self.key, n, s, body + tag, VAR)
        if quarantine is None:                      # tag check
            return False
        if seq_ad != seq_nonce or not seq_ad > self.last_seq:   # sequence check
            return False
        self.last_seq = seq_ad                      # used up before any write
        for i in range(0, len(quarantine), 8):
            self.acc.write(*unpack(quarantine[i:i + 8]))
        return True


def main():
    pairs = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 2026
    rng = random.Random(seed)
    rules = ["R1", "R2", "R3", "R4"]
    names = {"R1": "each write: tag only",
             "R2": "each write: tag, forward-only counter",
             "R3": "each write: tag, consecutive counter",
             "R4": "whole job (WADJET rule)"}
    # per rule: attempts, attempts with any write released,
    # attempts in which the accelerator started with an unapproved configuration
    res = {a: {r: [0, 0, 0] for r in rules} for a in ("mix", "cut")}
    control = {r: 0 for r in rules}

    for _ in range(pairs):
        _checked.clear()
        key, epoch = os.urandom(16), os.urandom(8)
        X, Y = make_job(rng), make_job(rng)
        approved = (config_of(X), config_of(Y))

        auth = Authority(key, epoch)
        mx, my = auth.seal_each_write(X), auth.seal_each_write(Y)
        sx, bx, tx = auth.seal_whole_job(X)
        sy, by, ty = auth.seal_whole_job(Y)

        # control: an untouched approved job must run as approved under every rule
        for r in rules:
            acc = Accelerator()
            if r == "R4":
                WholeJobReceiver(key, epoch, acc).submit(sx, sx, bx, tx)
            else:
                rx = PerWriteReceiver(key, epoch, r, acc)
                for c, ct in mx:
                    rx.deliver(c, ct)
            control[r] += acc.started_with == approved[0]

        for k in range(1, N_REC):
            for attack in ("mix", "cut"):
                for r in rules:
                    acc = Accelerator()
                    if r == "R4":
                        gate = WholeJobReceiver(key, epoch, acc)
                        if attack == "mix":
                            body = bx[:8 * k] + by[8 * k:]
                            # try both approvals the software holds
                            gate.submit(sy, sy, body, ty)
                            gate.submit(sx, sx, body, tx)
                            before = 0
                        else:
                            gate.submit(sx, sx, bx, tx)        # job X in full
                            before = acc.writes
                            gate.submit(sy, sy, by[:8 * k], ty)
                    else:
                        rx = PerWriteReceiver(key, epoch, r, acc)
                        before = 0
                        if attack == "mix":
                            seq = mx[:k] + my[k:]
                        else:
                            for c, ct in mx:                   # job X in full
                                rx.deliver(c, ct)
                            before = acc.writes
                            seq = my[:k]
                        for c, ct in seq:
                            rx.deliver(c, ct)
                    row = res[attack][r]
                    row[0] += 1
                    row[1] += acc.writes > before
                    if attack == "mix":
                        row[2] += (acc.started_with is not None
                                   and acc.started_with not in approved)
                    else:
                        row[2] += acc.reg not in approved

    print(f"job format: {FORMAT} ({N_REC} writes)   pairs of approved jobs: {pairs}   seed: {seed}")
    print("control, untouched approved job runs as approved: "
          + ", ".join(f"{r} {control[r]}/{pairs}" for r in rules))
    for attack, title, col in (
            ("mix", "MIX: first k writes of job X, rest from job Y", "unapproved run"),
            ("cut", "CUT SHORT: job X in full, then only the first k writes of job Y",
             "registers mixed")):
        print("\n" + title)
        print(f"{'release rule':40s} {'attempts':>9s} {'writes reached':>15s} {col:>15s}")
        for r in rules:
            a, w, u = res[attack][r]
            print(f"{names[r]:40s} {a:9d} {w:15d} {u:15d}")


if __name__ == "__main__":
    main()
