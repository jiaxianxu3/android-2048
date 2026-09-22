# -*- coding: utf-8 -*-
"""
2048 双模式 —— 纯逻辑层（无 pygame 依赖，可在桌面 / Kivy / Android 共用）

  · 正方形模式 (Square): 4x4 格子，方向 left/right/up/down
  · 六边形模式 (Hex):    标准六边形蜂窝(边长3格=19格)，中心格为黑洞，
                         方向 E/W/NE/NW/SE/SW

本文件只负责"规则与状态"，不负责任何渲染。
"""

import random
import math
import os
import json

# ============================================================
# 缓动函数
# ============================================================
def ease_out_cubic(t):
    return 1 - (1 - t) ** 3

def ease_out_back(t):
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


SLIDE_MS = 120   # 滑动时长
POP_MS = 100     # 合并/新格弹跳时长

# ============================================================
# 通用"一段格子"滑行计划
#   ordered_cells: 单元格按"移动方向端"在前的顺序(索引0为最前端)
#   get_value(cell): 当前数值(0=空)
#   is_block(cell): 是否为黑洞/隔板
# 返回: (result, move_map, merge, gained)
# ============================================================
def slide_line_plan(ordered_cells, get_value, is_block):
    result = {}
    move_map = {}
    merge = set()
    gained = 0

    runs = []
    i = 0
    n = len(ordered_cells)
    while i < n:
        if is_block(ordered_cells[i]):
            runs.append(('B', i))
            i += 1
        else:
            j = i
            while j < n and not is_block(ordered_cells[j]):
                j += 1
            runs.append(('S', list(range(i, j))))
            i = j

    for run in runs:
        if run[0] == 'B':
            result[ordered_cells[run[1]]] = 'BLOCK'
            continue
        indices = run[1]
        tiles = [(idx, get_value(ordered_cells[idx]))
                 for idx in indices if get_value(ordered_cells[idx]) != 0]
        dest = 0
        k = 0
        while k < len(tiles):
            src_idx, v = tiles[k]
            if k + 1 < len(tiles) and tiles[k + 1][1] == v:
                dest_cell = ordered_cells[indices[dest]]
                result[dest_cell] = v * 2
                merge.add(dest_cell)
                gained += v * 2
                move_map[ordered_cells[src_idx]] = dest_cell
                move_map[ordered_cells[tiles[k + 1][0]]] = dest_cell
                k += 2
            else:
                dest_cell = ordered_cells[indices[dest]]
                result[dest_cell] = v
                move_map[ordered_cells[src_idx]] = dest_cell
                k += 1
            dest += 1
        for j in range(dest, len(indices)):
            result[ordered_cells[indices[j]]] = 0

    return result, move_map, merge, gained


# ============================================================
# 正方形模式
# ============================================================
class SquareBoard:
    SIZE = 4

    def __init__(self):
        self.grid = [[0] * self.SIZE for _ in range(self.SIZE)]
        self.score = 0
        self.won = False
        self.spawn()
        self.spawn()

    def snapshot(self):
        return {(r, c): self.grid[r][c] for r in range(self.SIZE) for c in range(self.SIZE)}

    def spawn(self):
        empties = [(r, c) for r in range(self.SIZE) for c in range(self.SIZE)
                   if self.grid[r][c] == 0]
        if not empties:
            return None
        r, c = random.choice(empties)
        v = 4 if random.random() < 0.1 else 2
        self.grid[r][c] = v
        return (r, c), v

    @staticmethod
    def _lines(direction):
        lines = []
        if direction in ('left', 'right'):
            for r in range(4):
                line = [(r, c) for c in range(4)]
                if direction == 'right':
                    line = line[::-1]
                lines.append(line)
        else:
            for c in range(4):
                line = [(r, c) for r in range(4)]
                if direction == 'down':
                    line = line[::-1]
                lines.append(line)
        return lines

    def plan_move(self, direction):
        before = self.snapshot()
        result = {}
        move_map = {}
        merge = set()
        gained = 0
        for line in self._lines(direction):
            res, mm, ml, g = slide_line_plan(
                line, lambda c: self.grid[c[0]][c[1]], lambda c: False)
            result.update(res)
            move_map.update(mm)
            merge |= ml
            gained += g
        final = {c: (0 if result.get(c) == 'BLOCK' else result.get(c, before[c]))
                 for c in before}
        moved = any(before[c] != final[c] for c in before)
        return dict(moved=moved, gained=gained, final=final,
                    move_map=move_map, merge=merge, before=before)

    def _apply_final(self, final):
        self.grid = [[final[(r, c)] for c in range(self.SIZE)] for r in range(self.SIZE)]

    def move(self, direction):
        plan = self.plan_move(direction)
        if not plan['moved']:
            return plan
        self._apply_final(plan['final'])
        self.score += plan['gained']
        cell = self.spawn()
        if not self.won and any(2048 in row for row in self.grid):
            self.won = True
        plan['spawn'] = cell
        return plan

    def can_move(self):
        if any(self.grid[r][c] == 0 for r in range(self.SIZE) for c in range(self.SIZE)):
            return True
        for d in ('left', 'right', 'up', 'down'):
            if self.plan_move(d)['moved']:
                return True
        return False

    def to_dict(self):
        return {"grid": [row[:] for row in self.grid],
                "score": self.score, "won": self.won}

    def load_dict(self, d):
        self.grid = [row[:] for row in d["grid"]]
        self.score = d["score"]
        self.won = d["won"]


# ============================================================
# 六边形模式 —— 标准六边形蜂窝 (边长 3 = 19 格)
# ============================================================
BLACK = (0, 0)

HEX_DIRS = {
    'E':  {'sort': lambda c: c[0], 'asc': False, 'key': lambda c: c[1]},
    'W':  {'sort': lambda c: c[0], 'asc': True,  'key': lambda c: c[1]},
    'NE': {'sort': lambda c: c[0], 'asc': False, 'key': lambda c: c[0] + c[1]},
    'SW': {'sort': lambda c: c[0], 'asc': True,  'key': lambda c: c[0] + c[1]},
    'NW': {'sort': lambda c: c[1], 'asc': True,  'key': lambda c: c[0]},
    'SE': {'sort': lambda c: c[1], 'asc': False, 'key': lambda c: c[0]},
}


class HexBoard:
    RADIUS = 2

    def __init__(self):
        self.cells = {}
        self.valid = set()
        R = self.RADIUS
        for r in range(-R, R + 1):
            qmin = max(-R, -R - r)
            qmax = min(R, R - r)
            for q in range(qmin, qmax + 1):
                self.valid.add((q, r))
        for c in self.valid:
            self.cells[c] = 0
        self.score = 0
        self.won = False
        self.spawn()
        self.spawn()

    def is_black(self, c):
        return c == BLACK

    def snapshot(self):
        return dict(self.cells)

    def spawn(self):
        empties = [c for c in self.valid if self.cells[c] == 0 and not self.is_black(c)]
        if not empties:
            return None
        c = random.choice(empties)
        v = 4 if random.random() < 0.1 else 2
        self.cells[c] = v
        return (c, v)

    def plan_move(self, direction):
        before = self.snapshot()
        cfg = HEX_DIRS[direction]
        result = {}
        move_map = {}
        merge = set()
        gained = 0
        lines = {}
        for c in self.valid:
            lines.setdefault(cfg['key'](c), []).append(c)
        for key, line in lines.items():
            ordered = sorted(line, key=cfg['sort'], reverse=(not cfg['asc']))
            res, mm, ml, g = slide_line_plan(ordered, lambda c: self.cells[c], self.is_black)
            result.update(res)
            move_map.update(mm)
            merge |= ml
            gained += g
        final = {c: (0 if result.get(c) == 'BLOCK' else result.get(c, before[c]))
                 for c in before}
        moved = any(before[c] != final[c] for c in before)
        return dict(moved=moved, gained=gained, final=final,
                    move_map=move_map, merge=merge, before=before)

    def _apply_final(self, final):
        for c in self.valid:
            self.cells[c] = final[c]

    def move(self, direction):
        plan = self.plan_move(direction)
        if not plan['moved']:
            return plan
        self._apply_final(plan['final'])
        self.score += plan['gained']
        cell = self.spawn()
        if not self.won and any(self.cells[c] == 2048 for c in self.valid):
            self.won = True
        plan['spawn'] = cell
        return plan

    def can_move(self):
        if any(self.cells[c] == 0 and not self.is_black(c) for c in self.valid):
            return True
        for d in HEX_DIRS:
            if self.plan_move(d)['moved']:
                return True
        return False

    def to_dict(self):
        return {"cells": [[c[0], c[1], self.cells[c]] for c in self.valid],
                "score": self.score, "won": self.won}

    def load_dict(self, d):
        for c in self.valid:
            self.cells[c] = 0
        for q, r, v in d["cells"]:
            self.cells[(q, r)] = v
        self.score = d["score"]
        self.won = d["won"]


# ============================================================
# 颜色（0-255 整数元组，渲染层自行转 0-1 浮点）
# ============================================================
TILE_COLORS = {
    0: (0xcd, 0xc1, 0xb4),
    2: (0xee, 0xe4, 0xda), 4: (0xed, 0xe0, 0xc8), 8: (0xf2, 0xb1, 0x79),
    16: (0xf5, 0x95, 0x63), 32: (0xf6, 0x7c, 0x5f), 64: (0xf6, 0x5e, 0x3b),
    128: (0xed, 0xcf, 0x72), 256: (0xed, 0xcc, 0x61), 512: (0xed, 0xc8, 0x50),
    1024: (0xed, 0xc5, 0x3f), 2048: (0xed, 0xc2, 0x2e),
}
TEXT_DARK = (0x77, 0x6e, 0x65)
TEXT_LIGHT = (0xff, 0xff, 0xff)
BG = (0xfa, 0xf8, 0xef)
PANEL = (0xbb, 0xad, 0xa0)
BLACK_CELL = (0x20, 0x20, 0x20)


def tile_color(v):
    if v in TILE_COLORS:
        return TILE_COLORS[v]
    return (0x3c, 0x3a, 0x32)


# ============================================================
# 存档 / 读档（按模式分别保存上次未完成的游戏进度）
#   save_dir: 存档目录；不传则用本文件所在目录（桌面）。
#             Kivy/Android 应传入 App.user_data_dir。
# ============================================================
def _save_path(mode, save_dir=None):
    if save_dir is None:
        save_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(save_dir, "save_game_%s.json" % mode)


def _new_board(mode):
    return SquareBoard() if mode == 'square' else HexBoard()


def save_game(mode, board, save_dir=None):
    try:
        with open(_save_path(mode, save_dir), "w", encoding="utf-8") as f:
            json.dump({"mode": mode, "board": board.to_dict()}, f)
    except OSError:
        pass


def has_save(mode, save_dir=None):
    return os.path.exists(_save_path(mode, save_dir))


def load_game(mode, save_dir=None):
    try:
        with open(_save_path(mode, save_dir), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if data.get("mode") != mode:
        return None
    board = _new_board(mode)
    board.load_dict(data["board"])
    return board


def clear_save(mode, save_dir=None):
    try:
        os.remove(_save_path(mode, save_dir))
    except OSError:
        pass


# ============================================================
# 六边形蜂窝几何（尖顶正六边形，标准公式，保证不拉伸）
#   屏幕中心: px = size * sqrt(3) * (q + r/2), py = size * 1.5 * r
#   相邻六边形中心等距 = size * sqrt(3)，因此绘制出的是真正正六边形
# ============================================================
def hex_centers(valid, W, H, R_factor=0.94,
                top_reserve=110.0, bottom_reserve=40.0, side_margin=20.0):
    raw = {c: (math.sqrt(3) * (c[0] + c[1] / 2.0), 1.5 * c[1]) for c in valid}
    xs = [p[0] for p in raw.values()]
    ys = [p[1] for p in raw.values()]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    raw_w = maxx - minx
    raw_h = maxy - miny
    ext_w = math.sqrt(3) * R_factor
    ext_h = 2.0 * R_factor
    avail_w = W - 2 * side_margin
    avail_h = H - top_reserve - bottom_reserve
    size = min(avail_w / (raw_w + ext_w), avail_h / (raw_h + ext_h))
    size = max(size, 6.0)
    cx0 = (minx + maxx) / 2.0
    cy0 = (miny + maxy) / 2.0
    ox = W / 2.0
    oy = top_reserve + avail_h / 2.0
    pos = {c: (ox + (p[0] - cx0) * size, oy + (p[1] - cy0) * size)
           for c, p in raw.items()}
    return pos, size


# ============================================================
# 滑动方向识别（触摸/鼠标用）
#   dx, dy: 屏幕像素位移，约定 dy>0 表示"向下"（与 pygame 一致）。
#   调用方需把平台坐标(y 向上)换算成 dy = start_y - end_y。
# ============================================================
def swipe_dir(dx, dy, md):
    if md == 'square':
        if abs(dx) > abs(dy):
            return 'right' if dx > 0 else 'left'
        else:
            return 'down' if dy > 0 else 'up'
    ang = math.degrees(math.atan2(dy, dx))
    cands = {'E': 0.0, 'NE': -60.0, 'NW': -120.0, 'SE': 60.0, 'SW': 120.0, 'W': 180.0}
    best, bestd = None, 999
    for name, a in cands.items():
        d = abs((ang - a + 180) % 360 - 180)
        if d < bestd:
            bestd, best = d, name
    return best
