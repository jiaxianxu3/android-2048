# -*- coding: utf-8 -*-
"""
2048 双模式 —— Kivy / Android 版
  · 复用 game_logic.py 的纯逻辑（正方形 / 六边形蜂窝）
  · 触摸滑动 + 屏幕方向键控制
  · 平滑滑动动画（复用桌面版的缓动数学）
  · 按模式分别存档（写到 App.user_data_dir）

构建 APK 见同目录 buildozer.spec 与 .github/workflows/build-apk.yml
"""

import os
import math
import time

import game_logic as G

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.widget import Widget
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.graphics import Color, Rectangle, RoundedRectangle, Mesh
from kivy.core.text import Label as CoreLabel
from kivy.clock import Clock
from kivy.metrics import dp, sp


def rgba(rgb, a=1.0):
    return (rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0, a)


# ============================================================
# 棋盘视图（canvas 绘制 + 滑动动画 + 触摸滑动）
# ============================================================
class BoardView(Widget):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.mode = None          # 'square' / 'hex'
        self.board = None
        self.layout = None
        self.anim = None          # 移动动画计划
        self.anim_done_cb = None  # 动画结束回调
        self.swipe_start = None
        self._tex_cache = {}
        self.bind(size=self._on_size)
        Clock.schedule_interval(self._tick, 1 / 60)

    # ---- 布局 ----
    def _on_size(self, *a):
        self.recompute_layout()
        self.redraw()

    def recompute_layout(self):
        if self.mode is None or self.board is None:
            return
        if self.mode == 'square':
            W, H = self.width, self.height
            gap = max(6.0, min(W, H) * 0.02)
            avail = min(W, H) - 2 * gap
            CELL = (avail - 4 * gap) / 4.0
            CELL = max(CELL, 18.0)
            board_px = 4 * CELL + 5 * gap
            left = (W - board_px) / 2.0
            top = (H - board_px) / 2.0
            self.layout = dict(type='square', left=left, top=top,
                               CELL=CELL, gap=gap, board_px=board_px)
        else:
            pos, size = G.hex_centers(self.board.valid, self.width, self.height,
                                      top_reserve=10.0, bottom_reserve=10.0,
                                      side_margin=10.0)
            self.layout = dict(type='hex', pos=pos, size=size)

    def set_board(self, mode, board):
        self.mode = mode
        self.board = board
        self.anim = None
        self.recompute_layout()
        self.redraw()

    def set_anim(self, plan):
        plan = dict(plan)
        plan['t0'] = time.perf_counter()
        self.anim = plan
        self.redraw()

    def cell_center(self, cell):
        if self.layout['type'] == 'square':
            l = self.layout
            r, c = cell
            return (l['left'] + c * (l['CELL'] + l['gap']) + l['CELL'] / 2,
                    l['top'] + r * (l['CELL'] + l['gap']) + l['CELL'] / 2)
        return self.layout['pos'][cell]

    def value_at(self, cell):
        if self.mode == 'square':
            return self.board.grid[cell[0]][cell[1]]
        return self.board.cells.get(cell, 0)

    # ---- 绘制基元 ----
    def _round_rect(self, x, y, w, h, rgb, radius=6.0):
        # x,y 为 y-down 坐标系(原点左上)下的左上角
        sy_top = self.height - (y + h)
        r = [radius, radius, radius, radius]
        with self.canvas:
            Color(*rgba(rgb))
            RoundedRectangle(pos=(x, sy_top), size=(w, h), radius=r)

    def _hex(self, cx, cy, size, rgb):
        # cx,cy 为 y-down 坐标
        corners = []
        for i in range(6):
            ang = math.radians(60 * i - 30)
            corners.append((cx + size * math.cos(ang), cy + size * math.sin(ang)))
        verts = [cx, cy]
        for (px, py) in corners:
            verts += [px, self.height - py]
        verts += [corners[0][0], self.height - corners[0][1]]
        indices = []
        for i in range(1, 7):
            indices += [0, i, i + 1]
        with self.canvas:
            Color(*rgba(rgb))
            Mesh(vertices=verts, indices=indices, mode='triangles',
                 fmt=[(b'v_pos', 2, 'float')])

    def _tex(self, text, fs, rgb):
        key = (text, fs, rgb)
        if key in self._tex_cache:
            return self._tex_cache[key]
        lbl = CoreLabel(text=text, font_size=fs, bold=True,
                        color=(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0, 1.0))
        lbl.refresh()
        self._tex_cache[key] = lbl.texture
        return lbl.texture

    def _draw_tile(self, cx, cy, value, scale):
        if value == 0:
            return
        rgb = G.tile_color(value)
        tc = G.TEXT_DARK if value < 8 else G.TEXT_LIGHT
        if self.mode == 'square':
            CELL = self.layout['CELL']
            s = CELL * scale
            self._round_rect(cx - s / 2, cy - s / 2, s, s, rgb)
            fs = int(CELL * 0.42 * scale) if value < 1000 else int(CELL * 0.33 * scale)
        else:
            size = self.layout['size'] * 0.94 * scale
            self._hex(cx, cy, size, rgb)
            fs = int(self.layout['size'] * 0.7 * scale) if value < 1000 else int(self.layout['size'] * 0.5 * scale)
        fs = max(fs, 9)
        tex = self._tex(str(value), fs, tc)
        sx = cx - tex.width / 2.0
        sy = self.height - (cy + tex.height / 2.0)
        with self.canvas:
            Rectangle(texture=tex, pos=(sx, sy), size=tex.size)

    # ---- 空槽背景 ----
    def _draw_empty(self):
        if self.mode == 'square':
            l = self.layout
            pad = l['gap']
            self._round_rect(l['left'] - pad, l['top'] - pad,
                             l['board_px'] + 2 * pad, l['board_px'] + 2 * pad,
                             G.PANEL, radius=10)
            for r in range(4):
                for c in range(4):
                    cx = l['left'] + c * (l['CELL'] + l['gap']) + l['CELL'] / 2
                    cy = l['top'] + r * (l['CELL'] + l['gap']) + l['CELL'] / 2
                    self._round_rect(cx - l['CELL'] / 2, cy - l['CELL'] / 2,
                                     l['CELL'], l['CELL'], G.TILE_COLORS[0])
        else:
            for cell in self.board.valid:
                cx, cy = self.layout['pos'][cell]
                if self.board.is_black(cell):
                    self._hex(cx, cy, self.layout['size'] * 0.94, G.BLACK_CELL)
                else:
                    self._hex(cx, cy, self.layout['size'] * 0.94, G.TILE_COLORS[0])

    # ---- 静态棋盘 ----
    def _draw_static(self):
        self._draw_empty()
        if self.mode == 'square':
            for r in range(4):
                for c in range(4):
                    v = self.board.grid[r][c]
                    if v:
                        self._draw_tile(*self.cell_center((r, c)), v, 1.0)
        else:
            for cell in self.board.valid:
                if self.board.is_black(cell):
                    continue
                v = self.board.cells[cell]
                if v:
                    self._draw_tile(*self.cell_center(cell), v, 1.0)

    # ---- 动画棋盘 ----
    def _draw_animated(self):
        self._draw_empty()
        a = self.anim
        elapsed = (time.perf_counter() - a['t0']) * 1000.0
        before, final, move_map, merge = a['before'], a['final'], a['move_map'], a['merge']
        spawn = a.get('spawn')
        dest_receivers = {d for s, d in move_map.items() if s != d}

        if elapsed < G.SLIDE_MS:
            e = G.ease_out_cubic(elapsed / G.SLIDE_MS)
            for s, d in move_map.items():
                if s == d:
                    continue
                val = before[s]
                if val == 0:
                    continue
                c0 = self.cell_center(s)
                c1 = self.cell_center(d)
                cx = c0[0] + (c1[0] - c0[0]) * e
                cy = c0[1] + (c1[1] - c0[1]) * e
                self._draw_tile(cx, cy, val, 1.0)
            for cell, val in final.items():
                if val == 0:
                    continue
                if cell in merge:
                    continue
                if cell in dest_receivers:
                    continue
                if spawn and cell == spawn[0]:
                    continue
                self._draw_tile(*self.cell_center(cell), val, 1.0)
        else:
            pp = min(max((elapsed - G.SLIDE_MS) / G.POP_MS, 0.0), 1.0)
            for cell, val in final.items():
                if val == 0:
                    continue
                if spawn and cell == spawn[0]:
                    continue
                scale = 1.0 + 0.15 * (1 - G.ease_out_cubic(pp)) if cell in merge else 1.0
                self._draw_tile(*self.cell_center(cell), val, scale)
            if spawn:
                sval = G.ease_out_cubic(pp)
                self._draw_tile(*self.cell_center(spawn[0]), spawn[1], sval)

    def redraw(self):
        if self.mode is None or self.board is None or self.layout is None:
            self.canvas.clear()
            return
        self.canvas.clear()
        if self.anim is not None:
            self._draw_animated()
        else:
            self._draw_static()

    def _tick(self, dt):
        if self.anim is not None:
            elapsed = (time.perf_counter() - self.anim['t0']) * 1000.0
            if elapsed >= G.SLIDE_MS + G.POP_MS:
                self.anim = None
                self.redraw()
                # 注意: 保留 anim_done_cb, 以便后续(被排队的)动画完成时仍能回调
                if self.anim_done_cb is not None:
                    self.anim_done_cb()
            else:
                self.redraw()

    # ---- 触摸滑动 ----
    def on_touch_down(self, touch):
        if self.mode is None:
            return False
        self.swipe_start = (touch.x, touch.y)
        return True

    def on_touch_up(self, touch):
        if self.swipe_start is None:
            return False
        sx, sy = self.swipe_start
        self.swipe_start = None
        dx = touch.x - sx
        dy = sy - touch.y          # 翻转：Kivy y 向上 -> 向下为正
        if abs(dx) > 24 or abs(dy) > 24:
            d = G.swipe_dir(dx, dy, self.mode)
            if self.callback_move:
                self.callback_move(d)
        return True


# ============================================================
# 游戏界面
# ============================================================
class GameScreen(Screen):
    def __init__(self, app_ref, **kw):
        super().__init__(**kw)
        self.app = app_ref
        root = BoxLayout(orientation='vertical', padding=dp(8), spacing=dp(6))

        # 顶栏
        bar = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(60), spacing=dp(8))
        title = Label(text='2048', font_size=sp(30), color=(0.46, 0.43, 0.40, 1),
                      size_hint_x=None, width=dp(120), halign='left')
        self.score_label = Label(text='0', font_size=sp(24),
                                 color=(0.46, 0.43, 0.40, 1), size_hint_x=None, width=dp(90))
        btn_menu = Button(text='菜单', size_hint=(None, 1), width=dp(72), font_size=sp(16))
        btn_restart = Button(text='重开', size_hint=(None, 1), width=dp(72), font_size=sp(16))
        btn_menu.bind(on_release=lambda *a: self.app.goto_menu())
        btn_restart.bind(on_release=lambda *a: self.app.restart())
        bar.add_widget(title)
        bar.add_widget(self.score_label)
        bar.add_widget(Label(size_hint_x=1))
        bar.add_widget(btn_restart)
        bar.add_widget(btn_menu)
        root.add_widget(bar)

        # 棋盘
        self.board_view = BoardView()
        self.board_view.callback_move = self.app.do_move
        root.add_widget(self.board_view)

        # 控制区
        self.pad = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(120), spacing=dp(6))
        root.add_widget(self.pad)

        self.add_widget(root)
        self.overlay = None

    def build_pad(self, mode):
        self.pad.clear_widgets()
        if mode == 'square':
            labels = [('↑', 'up'), ('←', 'left'), ('→', 'right'), ('↓', 'down')]
            for txt, d in labels:
                b = Button(text=txt, font_size=sp(26))
                b.bind(on_release=lambda *a, _d=d: self.app.do_move(_d))
                self.pad.add_widget(b)
        else:
            order = [('左上', 'NW'), ('右上', 'NE'),
                     ('左', 'W'), ('右', 'E'),
                     ('左下', 'SW'), ('右下', 'SE')]
            grid = GridLayout(cols=2, spacing=dp(6))
            for txt, d in order:
                b = Button(text=txt, font_size=sp(18))
                b.bind(on_release=lambda *a, _d=d: self.app.do_move(_d))
                grid.add_widget(b)
            self.pad.add_widget(grid)

    def show_game_over(self, score):
        if self.overlay:
            return
        ov = FloatLayout()
        with ov.canvas.before:
            Color(0.98, 0.97, 0.94, 0.88)
            self._ov_rect = Rectangle(pos=ov.pos, size=ov.size)
        ov.bind(pos=lambda inst, p: setattr(self._ov_rect, 'pos', p))
        ov.bind(size=lambda inst, s: setattr(self._ov_rect, 'size', s))
        box = BoxLayout(orientation='vertical', spacing=dp(12),
                        size_hint=(0.8, 0.5), pos_hint={'center_x': 0.5, 'center_y': 0.5})
        msg = Label(text='游戏结束', font_size=sp(34), color=(0.46, 0.43, 0.40, 1))
        sc = Label(text='最终得分 %d' % score, font_size=sp(22), color=(0.46, 0.43, 0.40, 1))
        b1 = Button(text='重开', size_hint=(0.6, None), height=dp(48), font_size=sp(18))
        b2 = Button(text='菜单', size_hint=(0.6, None), height=dp(48), font_size=sp(18))
        b1.bind(on_release=lambda *a: self.app.restart())
        b2.bind(on_release=lambda *a: self.app.goto_menu())
        box.add_widget(msg); box.add_widget(sc); box.add_widget(b1); box.add_widget(b2)
        ov.add_widget(box)
        self.add_widget(ov)
        self.overlay = ov

    def hide_overlay(self):
        if self.overlay:
            self.remove_widget(self.overlay)
            self.overlay = None


# ============================================================
# 菜单界面
# ============================================================
class MenuScreen(Screen):
    def __init__(self, app_ref, **kw):
        super().__init__(**kw)
        self.app = app_ref
        self.box = BoxLayout(orientation='vertical', padding=dp(24), spacing=dp(14))
        self.add_widget(self.box)

    def refresh(self):
        self.box.clear_widgets()
        title = Label(text='2048', font_size=sp(52), color=(0.46, 0.43, 0.40, 1))
        sub = Label(text='双模式 · 触摸滑动 / 方向键', font_size=sp(18),
                    color=(0.56, 0.53, 0.49, 1))
        self.box.add_widget(title)
        self.box.add_widget(sub)
        self.box.add_widget(Label(size_hint_y=None, height=dp(10)))

        items = [
            ('正方形模式 (新游戏)', '4x4  ·  滑动或方向键', lambda: self.app.start_game('square', None)),
            ('六边形模式 (新游戏)', '蜂窝19格  ·  中心黑格', lambda: self.app.start_game('hex', None)),
        ]
        if G.has_save('square', self.app.save_dir):
            items.append(('继续正方形模式', '载入上次进度',
                          lambda: self.app.start_game('square', 'continue')))
        if G.has_save('hex', self.app.save_dir):
            items.append(('继续六边形模式', '载入上次进度',
                          lambda: self.app.start_game('hex', 'continue')))

        for head, desc, cb in items:
            row = BoxLayout(orientation='vertical', spacing=dp(2),
                            size_hint_y=None, height=dp(72))
            b = Button(text=head, font_size=sp(20), size_hint_y=0.66)
            d = Label(text=desc, font_size=sp(14), color=(0.56, 0.53, 0.49, 1), size_hint_y=0.34)
            b.bind(on_release=lambda *a, _cb=cb: _cb())
            row.add_widget(b); row.add_widget(d)
            self.box.add_widget(row)

        self.box.add_widget(Label(size_hint_y=1))
        tip = Label(text='正方形: 上下左右滑动  六边形: 六向滑动', font_size=sp(14),
                    color=(0.66, 0.61, 0.55, 1))
        self.box.add_widget(tip)


# ============================================================
# 应用
# ============================================================
class Game2048App(App):
    def build(self):
        self.save_dir = self.user_data_dir
        self.mode = None
        self.board = None
        self.animating = False
        self.over = False
        self.queued = None

        self.sm = ScreenManager()
        self.menu = MenuScreen(name='menu', app_ref=self)
        self.game = GameScreen(name='game', app_ref=self)
        self.sm.add_widget(self.menu)
        self.sm.add_widget(self.game)
        return self.sm

    def on_start(self):
        self.menu.refresh()

    # ---- 流程 ----
    def start_game(self, mode, source):
        if source == 'continue':
            board = G.load_game(mode, self.save_dir)
            if board is None:
                board = G._new_board(mode)
                G.save_game(mode, board, self.save_dir)
        else:
            board = G._new_board(mode)
            G.save_game(mode, board, self.save_dir)
        self.mode = mode
        self.board = board
        self.animating = False
        self.over = False
        self.queued = None
        self.game.hide_overlay()
        self.game.build_pad(mode)
        self.game.score_label.text = str(board.score)
        self.game.board_view.set_board(mode, board)
        self.game.board_view.anim_done_cb = self.on_anim_finished
        self.sm.current = 'game'

    def do_move(self, direction):
        if self.board is None or self.over:
            return
        if self.animating:
            self.queued = direction
            return
        self._perform(direction)

    def _perform(self, direction):
        plan = self.board.move(direction)
        if not plan['moved']:
            return
        self.animating = True
        self.game.score_label.text = str(self.board.score)
        self.game.board_view.set_anim(plan)
        G.save_game(self.mode, self.board, self.save_dir)

    def on_anim_finished(self):
        self.animating = False
        if not self.board.can_move():
            self.over = True
            G.clear_save(self.mode, self.save_dir)
            self.game.show_game_over(self.board.score)
            return
        if self.queued is not None:
            d = self.queued
            self.queued = None
            self._perform(d)

    def restart(self):
        self.start_game(self.mode, None)

    def goto_menu(self):
        self.over = False
        self.animating = False
        self.queued = None
        self.game.hide_overlay()
        self.menu.refresh()
        self.sm.current = 'menu'


if __name__ == '__main__':
    Game2048App().run()
