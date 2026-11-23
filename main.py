# -*- coding: utf-8 -*-
"""CodeForge - a mobile code editor for Python, JavaScript and HTML.

* Multi-tab editor with syntax highlighting, line numbers, auto-indent,
  bracket / tag auto-closing, find & replace, comment toggle, undo / redo.
* Runs Python in-app (console with input() support and a Stop button).
* Runs HTML / JavaScript in a built-in Android WebView with a live console.
* Built as one APK for both arm64-v8a (64-bit) and armeabi-v7a (32-bit).
"""
import os
import re
import sys
import json
import time
import ctypes
import shutil
import builtins
import tempfile
import linecache
import threading
import traceback
import webbrowser

from kivy.config import Config

Config.set('kivy', 'exit_on_escape', '0')
if os.environ.get('CODEFORGE_TEST'):
    Config.set('graphics', 'width', '360')
    Config.set('graphics', 'height', '740')

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.core.window import Window
from kivy.event import EventDispatcher
from kivy.graphics import Color, Rectangle, RoundedRectangle, Line
from kivy.metrics import dp, sp
from kivy.properties import NumericProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.codeinput import CodeInput
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.recycleview import RecycleView
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import platform, get_color_from_hex, escape_markup

from pygments import lexers
from pygments.style import Style
from pygments.token import (Token, Comment, Keyword, Name, String, Number,
                            Operator, Punctuation, Generic, Error)

ANDROID = platform == 'android'
MONO = 'data/fonts/RobotoMono-Regular.ttf'
APP_VERSION = '1.0.0'

# --------------------------------------------------------------------------
#  Theme
# --------------------------------------------------------------------------
PALETTES = {
    'dark': dict(
        bg='#1a1535', panel='#130f2a', bar='#221b45', bar2='#2d2560',
        text='#e9e6ff', dim='#8f89bd', accent='#19c3b1', accent2='#3ddc84',
        accent_text='#06231f', danger='#ff6b6b', border='#362d6b',
        hl='#ffffff12', sel='#19c3b155', cursor='#3ddc84', warn='#ffd166'),
    'light': dict(
        bg='#fbfcfd', panel='#eef2f4', bar='#ffffff', bar2='#e2e9ee',
        text='#1b2230', dim='#6b7688', accent='#0e9f8e', accent2='#1f9d55',
        accent_text='#ffffff', danger='#d64545', border='#d3dce2',
        hl='#00000010', sel='#0e9f8e44', cursor='#0e9f8e', warn='#b7791f'),
}


class Theme(EventDispatcher):
    rev = NumericProperty(0)
    name = StringProperty('dark')

    def c(self, key):
        return get_color_from_hex(PALETTES[self.name][key])

    def hex(self, key):
        return PALETTES[self.name][key]

    def set(self, name):
        if name in PALETTES:
            self.name = name
            self.rev += 1


THEME = Theme()


def make_style(dark):
    if dark:
        k = dict(base='#e9e6ff', comment='#7a74a8', kw='#4ee3c1',
                 fn='#6cb6ff', cls='#7dd3fc', builtin='#8fe9ff',
                 deco='#ffd166', string='#a3e635', num='#ffb86c',
                 op='#c4b5fd', punc='#b6b1e0', tag='#4ee3c1',
                 attr='#6cb6ff', err='#ff6b6b', bg='#1a1535')
    else:
        k = dict(base='#1b2230', comment='#8a94a6', kw='#0a7d6e',
                 fn='#1d5fd1', cls='#0d6cae', builtin='#0b7285',
                 deco='#b7791f', string='#2f8a2f', num='#c25b00',
                 op='#6b46c1', punc='#4a5568', tag='#0a7d6e',
                 attr='#1d5fd1', err='#d64545', bg='#fbfcfd')
    styles = {
        Token: k['base'],
        Comment: 'italic ' + k['comment'],
        Comment.Preproc: k['deco'],
        Keyword: 'bold ' + k['kw'],
        Keyword.Constant: k['num'],
        Keyword.Type: k['cls'],
        Operator: k['op'],
        Operator.Word: 'bold ' + k['kw'],
        Punctuation: k['punc'],
        Name: k['base'],
        Name.Builtin: k['builtin'],
        Name.Builtin.Pseudo: k['kw'],
        Name.Function: k['fn'],
        Name.Class: 'bold ' + k['cls'],
        Name.Decorator: k['deco'],
        Name.Exception: k['err'],
        Name.Tag: 'bold ' + k['tag'],
        Name.Attribute: k['attr'],
        Name.Constant: k['num'],
        Name.Variable: k['base'],
        String: k['string'],
        String.Doc: 'italic ' + k['comment'],
        String.Escape: k['num'],
        String.Regex: k['num'],
        Number: k['num'],
        Generic.Error: k['err'],
        Error: k['err'],
    }
    return type('ForgeStyle', (Style,), {
        'background_color': k['bg'], 'styles': styles})


STYLE_DARK = make_style(True)
STYLE_LIGHT = make_style(False)

# --------------------------------------------------------------------------
#  Languages
# --------------------------------------------------------------------------
LANGS = {
    '.py': ('Python', lexers.PythonLexer, '#'),
    '.pyw': ('Python', lexers.PythonLexer, '#'),
    '.js': ('JavaScript', lexers.JavascriptLexer, '//'),
    '.mjs': ('JavaScript', lexers.JavascriptLexer, '//'),
    '.json': ('JSON', lexers.JsonLexer, None),
    '.html': ('HTML', lexers.HtmlLexer, None),
    '.htm': ('HTML', lexers.HtmlLexer, None),
    '.css': ('CSS', lexers.CssLexer, None),
    '.md': ('Markdown', lexers.MarkdownLexer, None),
    '.txt': ('Text', lexers.TextLexer, None),
}
RUNNABLE = ('Python', 'JavaScript', 'HTML')
VOID_TAGS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
             'link', 'meta', 'param', 'source', 'track', 'wbr', '!doctype'}
PAIRS = {'(': ')', '[': ']', '{': '}', '"': '"', "'": "'"}

TEMPLATES = {
    'Python': ('main.py',
               '# Python 3 - tap RUN to execute\n\n'
               'def greet(name):\n'
               '    return f"Hello, {name}!"\n\n\n'
               'if __name__ == "__main__":\n'
               '    print(greet("CodeForge"))\n'),
    'JavaScript': ('script.js',
                   '// JavaScript - tap RUN to execute\n\n'
                   'const greet = (name) => `Hello, ${name}!`;\n'
                   'console.log(greet("CodeForge"));\n'),
    'HTML': ('index.html',
             '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
             '  <meta charset="UTF-8">\n'
             '  <meta name="viewport" content="width=device-width, '
             'initial-scale=1">\n'
             '  <title>My Page</title>\n'
             '  <style>\n'
             '    body { font-family: sans-serif; text-align: center;\n'
             '           padding: 40px; background: #fbfcfd; }\n'
             '    h1 { color: #0e9f8e; }\n'
             '  </style>\n</head>\n<body>\n'
             '  <h1>Hello, CodeForge</h1>\n'
             '  <button onclick="console.log(\'clicked\')">Tap me</button>\n'
             '</body>\n</html>\n'),
    'Blank': ('notes.txt', ''),
}


def lang_of(name):
    ext = os.path.splitext(name)[1].lower()
    return LANGS.get(ext, ('Text', lexers.TextLexer, None))


# --------------------------------------------------------------------------
#  Small UI toolkit
# --------------------------------------------------------------------------
def blend(c1, c2, t):
    return [c1[i] + (c2[i] - c1[i]) * t for i in range(4)]


class Btn(ButtonBehavior, Label):
    """Flat, rounded, theme-aware button."""

    def __init__(self, text='', kind='flat', radius=8, **kw):
        kw.setdefault('font_size', sp(13))
        kw.setdefault('halign', 'center')
        kw.setdefault('valign', 'middle')
        super().__init__(text=text, **kw)
        self.kind = kind
        self._radius = dp(radius)
        with self.canvas.before:
            self._col = Color(0, 0, 0, 1)
            self._rect = RoundedRectangle(radius=[self._radius])
        self.bind(pos=self._layout, size=self._layout, state=self._paint)
        self.bind(size=self._text_size)
        self.apply_theme()

    def _text_size(self, *a):
        self.text_size = (max(0, self.width - dp(6)), self.height)

    def _layout(self, *a):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def _bg_key(self):
        return {'flat': 'bar2', 'accent': 'accent', 'danger': 'danger',
                'ghost': 'bar', 'plain': 'panel', 'good': 'accent2'}.get(
            self.kind, 'bar2')

    def _paint(self, *a):
        base = THEME.c(self._bg_key())
        if self.kind == 'clear':
            base = [0, 0, 0, 0]
        if self.state == 'down':
            base = blend(base, THEME.c('text'), 0.22)
        self._col.rgba = base

    def apply_theme(self):
        if self.kind in ('accent', 'good'):
            self.color = THEME.c('accent_text')
        elif self.kind == 'danger':
            self.color = (1, 1, 1, 1)
        else:
            self.color = THEME.c('text')
        self._paint()


class ListBtn(Btn):
    """Left-aligned list row."""

    def __init__(self, text='', kind='plain', **kw):
        kw.setdefault('halign', 'left')
        kw.setdefault('markup', True)
        kw.setdefault('font_size', sp(14))
        super().__init__(text=text, kind=kind, radius=6, **kw)
        self.shorten = True
        self.shorten_from = 'right'
        self.padding = (dp(12), 0)

    def _text_size(self, *a):
        self.text_size = (max(0, self.width - dp(24)), self.height)


class Field(TextInput):
    def __init__(self, **kw):
        kw.setdefault('multiline', False)
        kw.setdefault('font_size', sp(14))
        kw.setdefault('write_tab', False)
        kw.setdefault('padding', [dp(10), dp(10), dp(10), dp(10)])
        kw.setdefault('background_normal', '')
        kw.setdefault('background_active', '')
        kw.setdefault('use_bubble', True)
        super().__init__(**kw)
        self.apply_theme()

    def apply_theme(self):
        self.background_color = THEME.c('panel')
        self.foreground_color = THEME.c('text')
        self.hint_text_color = THEME.c('dim')
        self.cursor_color = THEME.c('cursor')
        self.selection_color = THEME.c('sel')


class Bar(BoxLayout):
    """Background-coloured container."""

    def __init__(self, key='bar', **kw):
        super().__init__(**kw)
        self.key = key
        with self.canvas.before:
            self._col = Color(0, 0, 0, 1)
            self._rect = Rectangle()
        self.bind(pos=self._upd, size=self._upd)
        self.apply_theme()

    def _upd(self, *a):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def apply_theme(self):
        self._col.rgba = THEME.c(self.key)


class Txt(Label):
    def __init__(self, text='', key='text', **kw):
        kw.setdefault('font_size', sp(12))
        super().__init__(text=text, **kw)
        self.key = key
        self.apply_theme()

    def apply_theme(self):
        self.color = THEME.c(self.key)


class Card(BoxLayout):
    def __init__(self, **kw):
        kw.setdefault('orientation', 'vertical')
        kw.setdefault('padding', dp(12))
        kw.setdefault('spacing', dp(8))
        super().__init__(**kw)
        with self.canvas.before:
            self._bc = Color(0, 0, 0, 1)
            self._br = RoundedRectangle(radius=[dp(14)])
            self._fc = Color(0, 0, 0, 1)
            self._fr = RoundedRectangle(radius=[dp(13)])
        self.bind(pos=self._upd, size=self._upd)
        self.apply_theme()

    def _upd(self, *a):
        self._br.pos = self.pos
        self._br.size = self.size
        self._fr.pos = (self.x + dp(1), self.y + dp(1))
        self._fr.size = (self.width - dp(2), self.height - dp(2))

    def apply_theme(self):
        self._bc.rgba = THEME.c('border')
        self._fc.rgba = THEME.c('bar')


def themed(widget):
    """Apply theme to widget and all of its children."""
    for w in widget.walk(restrict=False):
        fn = getattr(w, 'apply_theme', None)
        if fn:
            fn()


class Sheet(ModalView):
    """Modal dialog with a card, title and content."""

    def __init__(self, title, content, size_hint=(.92, None), height=None,
                 **kw):
        super().__init__(size_hint=size_hint, auto_dismiss=True,
                         background='', background_color=(0, 0, 0, .55),
                         overlay_color=(0, 0, 0, .55), **kw)
        self.card = Card()
        head = BoxLayout(size_hint_y=None, height=dp(34))
        head.add_widget(Txt(title, 'accent', bold=True, font_size=sp(15),
                            halign='left', valign='middle'))
        head.children[0].bind(size=lambda w, s: setattr(
            w, 'text_size', (w.width, w.height)))
        x = Btn('Close', 'ghost', size_hint_x=None, width=dp(64))
        x.bind(on_release=lambda *a: self.dismiss())
        head.add_widget(x)
        self.card.add_widget(head)
        self.card.add_widget(content)
        self.add_widget(self.card)
        if height:
            self.size_hint_y = None
            self.height = height
        else:
            self.size_hint_y = .86
        themed(self)


def hrow(*widgets, **kw):
    row = BoxLayout(size_hint_y=None, height=kw.get('h', dp(42)),
                    spacing=dp(6))
    for w in widgets:
        row.add_widget(w)
    return row


# --------------------------------------------------------------------------
#  Editor widget
# --------------------------------------------------------------------------
class Editor(CodeInput):
    """CodeInput with auto-indent, auto-pairing and current-line highlight."""

    def __init__(self, app, lang, **kw):
        self.app = app
        self.lang = lang
        kw.setdefault('lexer', LANGS.get('.py')[1]())
        super().__init__(**kw)
        self.auto_indent = False
        self.do_wrap = False
        self.unfocus_on_touch = False
        self.tab_width = 4
        with self.canvas.after:
            self._hlc = Color(1, 1, 1, .07)
            self._hlr = Rectangle()
        for p in ('cursor', 'scroll_y', 'size', 'pos', 'font_size', 'focus'):
            self.bind(**{p: self._hl_update})

    # -- current line highlight -------------------------------------------
    def _hl_update(self, *a):
        try:
            dy = self.line_height + self.line_spacing
            row = self.cursor_row
            top = self.top - self.padding[1] + self.scroll_y - row * dy
            self._hlc.rgba = THEME.c('hl')
            self._hlr.pos = (self.x, top - dy)
            self._hlr.size = (self.width, dy)
        except Exception:
            pass

    def indent_unit(self):
        return ' ' * int(self.app.settings.get('tab_size', 4))

    # -- typing helpers ---------------------------------------------------
    def raw_insert(self, s):
        CodeInput.insert_text(self, s)

    def type_text(self, s):
        if self.selection_text:
            self.delete_selection()
        self.insert_text(s)

    def _char_at(self, idx):
        t = self.text
        return t[idx] if 0 <= idx < len(t) else ''

    def insert_text(self, substring, from_undo=False):
        st = self.app.settings
        if from_undo or self.readonly or not substring:
            return CodeInput.insert_text(self, substring, from_undo)
        if substring == '\t':
            unit = int(st.get('tab_size', 4))
            col = self.cursor_col
            return CodeInput.insert_text(
                self, ' ' * (unit - (col % unit)))
        if substring == '\n' and st.get('auto_indent', True):
            return self._smart_newline()
        if len(substring) == 1 and st.get('auto_pair', True):
            if self._auto_pair(substring):
                return
        return CodeInput.insert_text(self, substring)

    def _smart_newline(self):
        ci = self.cursor_index()
        t = self.text
        ls = t.rfind('\n', 0, ci) + 1
        before = t[ls:ci]
        indent = re.match(r'[ \t]*', before).group(0)
        stripped = before.rstrip()
        unit = self.indent_unit()
        extra = ''
        if self.lang == 'Python':
            if stripped.endswith(':'):
                extra = unit
        elif self.lang in ('JavaScript', 'JSON', 'CSS'):
            if stripped.endswith(('{', '(', '[')):
                extra = unit
        nxt = self._char_at(ci)
        if extra and nxt in ('}', ')', ']') and \
                stripped.endswith(('{', '(', '[')):
            CodeInput.insert_text(self, '\n' + indent + extra + '\n' + indent)
            for _ in range(len(indent) + 1):
                self.do_cursor_movement('cursor_left')
            return
        CodeInput.insert_text(self, '\n' + indent + extra)

    def _auto_pair(self, ch):
        ci = self.cursor_index()
        nxt = self._char_at(ci)
        prev = self._char_at(ci - 1)
        # type-over closing char
        if ch in PAIRS.values() and nxt == ch and not self.selection_text:
            self.do_cursor_movement('cursor_right')
            return True
        # HTML: auto close tag on '>'
        if ch == '>' and self.lang == 'HTML':
            t = self.text
            ls = t.rfind('\n', 0, ci) + 1
            m = re.search(r'<([A-Za-z][\w:-]*)(?:\s[^<>]*)?$', t[ls:ci])
            if m and not t[ls:ci].endswith('/') and \
                    m.group(1).lower() not in VOID_TAGS:
                tag = m.group(1)
                CodeInput.insert_text(self, '></%s>' % tag)
                for _ in range(len(tag) + 3):
                    self.do_cursor_movement('cursor_left')
                return True
            return False
        if ch in PAIRS:
            if self.selection_text:
                sel = self.selection_text
                self.delete_selection()
                CodeInput.insert_text(self, ch + sel + PAIRS[ch])
                return True
            if ch in ('"', "'"):
                if prev.isalnum() or prev == ch or \
                        (nxt and (nxt.isalnum() or nxt == ch)):
                    return False
            elif nxt and not (nxt.isspace() or nxt in ')]}>,;:.'):
                return False
            CodeInput.insert_text(self, ch + PAIRS[ch])
            self.do_cursor_movement('cursor_left')
            return True
        return False

    def do_backspace(self, from_undo=False, mode='bkspc'):
        if (self.app.settings.get('auto_pair', True) and mode == 'bkspc'
                and not from_undo and not self.selection_text):
            ci = self.cursor_index()
            a, b = self._char_at(ci - 1), self._char_at(ci)
            if a and PAIRS.get(a) == b:
                self.do_cursor_movement('cursor_right')
                CodeInput.do_backspace(self, from_undo, mode)
                CodeInput.do_backspace(self, from_undo, mode)
                return
        return CodeInput.do_backspace(self, from_undo, mode)

    # -- line operations --------------------------------------------------
    def _line_span(self):
        t = self.text
        if self.selection_text:
            a = min(self.selection_from, self.selection_to)
            b = max(self.selection_from, self.selection_to)
            if b > a and t[b - 1] == '\n':
                b -= 1
        else:
            a = b = self.cursor_index()
        s = t.rfind('\n', 0, a) + 1
        e = t.find('\n', b)
        if e == -1:
            e = len(t)
        return s, e

    def _replace_span(self, s, e, new):
        self.select_text(s, e)
        self.delete_selection()
        CodeInput.insert_text(self, new)
        self.select_text(s, s + len(new))

    def toggle_comment(self):
        prefix = lang_of('x.' + {'Python': 'py', 'JavaScript': 'js'}.get(
            self.lang, 'txt'))[2]
        s, e = self._line_span()
        lines = self.text[s:e].split('\n')
        if self.lang in ('HTML', 'CSS', 'Markdown'):
            def is_c(l):
                return l.strip().startswith('<!--') or \
                    l.strip().startswith('/*')
            opn, cls = ('<!-- ', ' -->') if self.lang != 'CSS' else \
                ('/* ', ' */')
            body = [l for l in lines if l.strip()]
            if body and all(is_c(l) for l in body):
                out = [re.sub(r'^(\s*)(<!--|/\*) ?', r'\1', l) for l in lines]
                out = [re.sub(r' ?(-->|\*/)\s*$', '', l) for l in out]
            else:
                out = [(re.match(r'\s*', l).group(0) + opn + l.strip() + cls)
                       if l.strip() else l for l in lines]
        elif prefix:
            body = [l for l in lines if l.strip()]
            if body and all(l.lstrip().startswith(prefix) for l in body):
                out = [re.sub(r'^(\s*)' + re.escape(prefix) + r' ?', r'\1',
                              l, count=1) for l in lines]
            else:
                out = [(re.match(r'\s*', l).group(0) + prefix + ' ' +
                        l.lstrip()) if l.strip() else l for l in lines]
        else:
            return False
        self._replace_span(s, e, '\n'.join(out))
        return True

    def indent_lines(self, outdent=False):
        s, e = self._line_span()
        unit = self.indent_unit()
        lines = self.text[s:e].split('\n')
        if outdent:
            out = []
            for l in lines:
                if l.startswith(unit):
                    out.append(l[len(unit):])
                else:
                    out.append(l.lstrip(' ')[0:0] + l[min(
                        len(l) - len(l.lstrip(' ')), len(unit)):])
        else:
            out = [(unit + l) if l.strip() else l for l in lines]
        self._replace_span(s, e, '\n'.join(out))

    def duplicate_line(self):
        s, e = self._line_span()
        chunk = self.text[s:e]
        self.cursor = self.get_cursor_from_index(e)
        self.select_text(e, e)
        CodeInput.insert_text(self, '\n' + chunk)

    def goto_line(self, n):
        n = max(1, min(int(n), len(self._lines)))
        self.cursor = (0, n - 1)
        self.select_text(0, 0)
        Clock.schedule_once(lambda dt: self._center_cursor(), 0)

    def _center_cursor(self):
        dy = self.line_height + self.line_spacing
        want = self.cursor_row * dy - self.height / 2
        maxy = max(0, self.minimum_height - self.height)
        self.scroll_y = max(0, min(maxy, want))


class Gutter(Widget):
    """Line-number gutter, drawn for visible lines only."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.size_hint_x = None
        self.width = dp(40)
        self.editor = None
        self._cache = {}
        self._trig = Clock.create_trigger(self.redraw, -1)
        self.bind(pos=self._trig, size=self._trig)

    def attach(self, ed):
        if self.editor is not None:
            for p in ('scroll_y', 'size', 'pos', 'cursor', 'font_size',
                      'text'):
                self.editor.unbind(**{p: self._trig})
        self.editor = ed
        self._cache = {}
        for p in ('scroll_y', 'size', 'pos', 'cursor', 'font_size', 'text'):
            ed.bind(**{p: self._trig})
        self._trig()

    def _tex(self, s, size, color):
        key = (s, size, tuple(color))
        t = self._cache.get(key)
        if t is None:
            if len(self._cache) > 600:
                self._cache = {}
            lab = CoreLabel(text=s, font_size=size, font_name=MONO,
                            color=color)
            lab.refresh()
            t = lab.texture
            self._cache[key] = t
        return t

    def redraw(self, *a):
        ed = self.editor
        self.canvas.clear()
        if ed is None or not self.app_show():
            return
        n = max(1, len(ed._lines))
        digits = max(2, len(str(n)))
        fs = max(sp(9), ed.font_size * .82)
        w = dp(16) + digits * fs * .62
        if abs(self.width - w) > 1:
            self.width = w
        dy = ed.line_height + ed.line_spacing
        first = max(0, int(ed.scroll_y // dy) - 1)
        last = min(n - 1, int((ed.scroll_y + ed.height) // dy) + 1)
        top0 = ed.top - ed.padding[1] + ed.scroll_y
        cur = ed.cursor_row
        dim = THEME.c('dim')
        acc = THEME.c('accent')
        with self.canvas:
            Color(*THEME.c('panel'))
            Rectangle(pos=self.pos, size=self.size)
            Color(*THEME.c('border'))
            Rectangle(pos=(self.right - dp(1), self.y),
                      size=(dp(1), self.height))
            for i in range(first, last + 1):
                tex = self._tex(str(i + 1), fs, acc if i == cur else dim)
                ytop = top0 - i * dy
                Color(1, 1, 1, 1)
                Rectangle(texture=tex, size=tex.size,
                          pos=(self.right - tex.width - dp(8),
                               ytop - dy + (dy - tex.height) / 2))

    def app_show(self):
        app = App.get_running_app()
        return bool(app and app.settings.get('line_numbers', True))


# --------------------------------------------------------------------------
#  Console
# --------------------------------------------------------------------------
def wrap_rows(text, cpl):
    """Rows needed for greedy word wrap at cpl characters per row."""
    rows, cur = 1, 0
    for word in re.split(r'(\s+)', text):
        n = len(word)
        if not n:
            continue
        if n > cpl:
            if cur:
                rows += 1
            rows += (n - 1) // cpl
            cur = n % cpl or cpl
        elif cur + n > cpl:
            if word.isspace():
                continue
            rows += 1
            cur = n
        else:
            cur += n
    return rows


class LogLine(Label):
    pass


class Console(BoxLayout):
    """Scrolling console backed by a RecycleView (handles big output)."""
    MAX_LINES = 3000

    def __init__(self, on_close=None, **kw):
        kw.setdefault('orientation', 'vertical')
        super().__init__(**kw)
        self.lines = []          # (text, kind)
        self.cur = ''
        self.cur_kind = 'out'
        self._trig = Clock.create_trigger(self._render, .05)
        head = Bar('bar', size_hint_y=None, height=dp(34),
                   padding=(dp(8), dp(2)), spacing=dp(6))
        self.title = Txt('CONSOLE', 'accent', bold=True, halign='left',
                         valign='middle')
        self.title.bind(size=lambda w, s: setattr(
            w, 'text_size', (w.width, w.height)))
        head.add_widget(self.title)
        for label, fn in (('Clear', self.clear), ('Copy', self.copy_all)):
            b = Btn(label, 'flat', size_hint_x=None, width=dp(58))
            b.bind(on_release=lambda w, f=fn: f())
            head.add_widget(b)
        if on_close:
            x = Btn('Hide', 'ghost', size_hint_x=None, width=dp(52))
            x.bind(on_release=lambda *a: on_close())
            head.add_widget(x)
        self.add_widget(head)
        self.rv = RecycleView(bar_width=dp(3), scroll_type=['bars',
                                                           'content'])
        lay = RecycleBoxLayout(default_size=(None, dp(18)),
                               default_size_hint=(1, None),
                               size_hint_y=None, orientation='vertical')
        lay.bind(minimum_height=lay.setter('height'))
        self.rv.add_widget(lay)
        self.rv.viewclass = LogLine
        self.back = Bar('panel')
        self.back.add_widget(self.rv)
        self.add_widget(self.back)
        self.rv.bind(width=lambda *a: self._trig())

    # -- API --------------------------------------------------------------
    def write(self, s, kind='out'):
        if not s:
            return
        if kind != self.cur_kind and self.cur:
            self._commit(self.cur, self.cur_kind)
            self.cur = ''
        self.cur_kind = kind
        parts = (self.cur + s).split('\n')
        for p in parts[:-1]:
            self._commit(p, kind)
        self.cur = parts[-1]
        self._trig()

    def line(self, s, kind='out'):
        self.write(s + '\n', kind)

    def _commit(self, text, kind):
        self.lines.append((text, kind))
        if len(self.lines) > self.MAX_LINES:
            del self.lines[:200]

    def clear(self):
        self.lines = []
        self.cur = ''
        self._trig()

    def plain(self):
        txt = '\n'.join(t for t, k in self.lines)
        if self.cur:
            txt += '\n' + self.cur
        return txt

    def copy_all(self):
        from kivy.core.clipboard import Clipboard
        Clipboard.copy(self.plain())
        app = App.get_running_app()
        if app:
            app.toast('Console copied')

    def apply_theme(self):
        self._trig()

    def _render(self, *a):
        fs = sp(12)
        lh = fs * 1.35
        width = max(dp(60), self.rv.width - dp(16))
        cpl = max(8, int(width / (fs * .66)))
        data = []
        allv = list(self.lines)
        if self.cur:
            allv.append((self.cur, self.cur_kind))
        colors = {'out': THEME.hex('text'), 'err': THEME.hex('danger'),
                  'info': THEME.hex('accent'), 'dim': THEME.hex('dim'),
                  'warn': THEME.hex('warn')}
        for text, kind in allv:
            rows = wrap_rows(text.expandtabs(4), cpl)
            data.append({
                'text': '[color=%s]%s[/color]' % (
                    colors.get(kind, colors['out']),
                    escape_markup(text.expandtabs(4)) or ' '),
                'markup': True, 'font_name': MONO, 'font_size': fs,
                'halign': 'left', 'valign': 'top',
                'text_size': (width, None),
                'padding_x': dp(8), 'size_hint_y': None,
                'height': rows * lh + dp(2)})
        stick = self.rv.scroll_y <= .02
        self.rv.data = data
        if stick:
            Clock.schedule_once(lambda dt: setattr(self.rv, 'scroll_y', 0),
                                .05)


# --------------------------------------------------------------------------
#  Python runner
# --------------------------------------------------------------------------
class PyRunner:
    def __init__(self, app):
        self.app = app
        self.thread = None
        self.buf = []
        self.lock = threading.Lock()
        self._flusher = None
        self._wait = None
        self.running = False

    # thread -> console plumbing
    def _emit(self, s, kind):
        with self.lock:
            self.buf.append((s, kind))

    def _flush(self, *a):
        with self.lock:
            items, self.buf = self.buf[:], []
        for s, k in items[:4000]:
            self.app.console_write(s, k)
        if len(items) > 4000:
            with self.lock:
                self.buf = items[4000:] + self.buf
        if not self.running and not self.buf:
            if self._flusher:
                self._flusher.cancel()
                self._flusher = None

    class _Out:
        def __init__(self, emit, kind):
            self.emit, self.kind = emit, kind
            self.encoding = 'utf-8'

        def write(self, s):
            if s:
                self.emit(str(s), self.kind)
            return len(s) if s else 0

        def flush(self):
            pass

        def isatty(self):
            return False

    def run(self, code, filename, cwd):
        if self.running:
            return
        self.running = True
        self.app.set_running(True)
        self._flusher = Clock.schedule_interval(self._flush, .08)
        self.thread = threading.Thread(
            target=self._worker, args=(code, filename, cwd), daemon=True)
        self.thread.start()

    def stop(self):
        if not self.running or not self.thread:
            return
        if self._wait is not None:
            self._wait.set()
        tid = self.thread.ident
        if tid is not None:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(
                ctypes.c_ulong(tid), ctypes.py_object(KeyboardInterrupt))

    def _input(self, prompt=''):
        if prompt:
            self._emit(str(prompt), 'out')
        ev = threading.Event()
        box = []
        self._wait = ev

        def done(v):
            box.append(v)
            ev.set()
        Clock.schedule_once(
            lambda dt: self.app.ask_input(str(prompt), done), 0)
        ev.wait()
        self._wait = None
        val = box[0] if box else ''
        self._emit(val + '\n', 'dim')
        return val

    def _worker(self, code, filename, cwd):
        t0 = time.time()
        old = (sys.stdout, sys.stderr, sys.argv[:], os.getcwd(),
               sys.path[:])
        sys.stdout = self._Out(self._emit, 'out')
        sys.stderr = self._Out(self._emit, 'err')
        sys.argv = [filename]
        try:
            os.chdir(cwd)
        except Exception:
            pass
        if cwd not in sys.path:
            sys.path.insert(0, cwd)
        b = dict(vars(builtins))
        b['input'] = self._input
        g = {'__name__': '__main__', '__file__': filename,
             '__builtins__': b}
        linecache.cache[filename] = (len(code), None,
                                     code.splitlines(True), filename)
        status = 'ok'
        try:
            exec(compile(code, filename, 'exec'), g)
        except SystemExit as e:
            if e.code not in (None, 0):
                self._emit('SystemExit: %s\n' % (e.code,), 'warn')
        except KeyboardInterrupt:
            status = 'stopped'
        except BaseException:
            status = 'error'
            et, ev, tb = sys.exc_info()
            tb = tb.tb_next if tb is not None else None
            self._emit(''.join(traceback.format_exception(et, ev, tb)),
                       'err')
        finally:
            try:
                sys.stdout, sys.stderr, sys.argv = old[0], old[1], old[2]
                os.chdir(old[3])
                sys.path[:] = old[4]
            except Exception:
                pass
            dt = time.time() - t0
            msg = {'ok': 'Finished in %.2fs', 'stopped':
                   'Stopped after %.2fs', 'error':
                   'Failed after %.2fs'}[status] % dt
            self._emit('\n' + msg + '\n', 'info' if status == 'ok'
                       else 'warn')
            self.running = False
            Clock.schedule_once(lambda d: self._finish(), .15)

    def _finish(self):
        self._flush()
        self.app.set_running(False)


# --------------------------------------------------------------------------
#  Web preview (Android WebView) for HTML / JavaScript
# --------------------------------------------------------------------------
CONSOLE_SHIM = (
    "(function(){var q=window.__cl=[];"
    "function f(a){try{return Array.prototype.map.call(a,function(x){"
    "if(typeof x==='string')return x;"
    "try{if(x instanceof Error)return x.stack||x.message;"
    "var j=JSON.stringify(x);return j===undefined?String(x):j}"
    "catch(e){return String(x)}}).join(' ')}catch(e){return ''}}"
    "['log','info','warn','error','debug'].forEach(function(k){"
    "var o=console[k];console[k]=function(){q.push([k,f(arguments)]);"
    "try{o.apply(console,arguments)}catch(e){}}});"
    "window.addEventListener('error',function(e){q.push(['error',"
    "(e.message||'Error')+(e.lineno?' (line '+e.lineno+')':'')])});"
    "window.addEventListener('unhandledrejection',function(e){"
    "q.push(['error','Unhandled promise rejection: '+"
    "(e.reason&&e.reason.stack||e.reason)])});"
    "window.alert=function(m){q.push(['info','alert: '+m])};"
    "})();")


def build_html(doc_lang, text):
    shim = '<script>%s</script>' % CONSOLE_SHIM
    if doc_lang == 'JavaScript':
        safe = text.replace('</script', '<\\/script')
        return ('<!DOCTYPE html><html><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,'
                'initial-scale=1"><title>JavaScript</title>' + shim +
                '</head><body style="font-family:sans-serif">'
                '<script>\n' + safe + '\n</script></body></html>')
    m = re.search(r'<head[^>]*>', text, re.I)
    if m:
        return text[:m.end()] + shim + text[m.end():]
    m = re.search(r'<html[^>]*>', text, re.I)
    if m:
        return text[:m.end()] + '<head>' + shim + '</head>' + text[m.end():]
    m = re.match(r'\s*<!doctype[^>]*>', text, re.I)
    if m:
        return text[:m.end()] + shim + text[m.end():]
    return shim + text


if ANDROID:
    from jnius import autoclass, PythonJavaClass, java_method
    from android.runnable import run_on_ui_thread

    class _JSCallback(PythonJavaClass):
        __javainterfaces__ = ['android/webkit/ValueCallback']
        __javacontext__ = 'app'

        def __init__(self, cb):
            super().__init__()
            self.cb = cb

        @java_method('(Ljava/lang/Object;)V')
        def onReceiveValue(self, value):
            try:
                self.cb(None if value is None else str(value))
            except Exception:
                pass


class Preview:
    """Wraps an Android WebView overlay (desktop: opens the browser)."""

    def __init__(self, app):
        self.app = app
        self.wv = None
        self.open = False
        self._cbs = []
        self._poll = None
        self._last = None

    def top_margin(self):
        return int(dp(52))

    def show(self, html, base_url):
        self._last = (html, base_url)
        self.open = True
        if not ANDROID:
            path = os.path.join(tempfile.gettempdir(), 'codeforge_preview.html')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(html)
            webbrowser.open('file://' + path)
            self.app.console_write('Opened in desktop browser (preview '
                                   'console only works on Android).\n',
                                   'dim')
            return
        self._android_show(html, base_url, self.top_margin())
        if self._poll is None:
            self._poll = Clock.schedule_interval(self._poll_logs, .4)

    if ANDROID:
        @run_on_ui_thread
        def _android_show(self, html, base_url, top):
            try:
                act = autoclass('org.kivy.android.PythonActivity').mActivity
                WebView = autoclass('android.webkit.WebView')
                WebViewClient = autoclass('android.webkit.WebViewClient')
                LP = autoclass('android.widget.FrameLayout$LayoutParams')
                self._destroy_now()
                wv = WebView(act)
                s = wv.getSettings()
                s.setJavaScriptEnabled(True)
                s.setDomStorageEnabled(True)
                s.setAllowFileAccess(True)
                try:
                    s.setAllowFileAccessFromFileURLs(True)
                    s.setAllowUniversalAccessFromFileURLs(True)
                except Exception:
                    pass
                s.setBuiltInZoomControls(False)
                s.setLoadWithOverviewMode(True)
                s.setUseWideViewPort(True)
                wv.setWebViewClient(WebViewClient())
                lp = LP(-1, -1)
                lp.topMargin = top
                act.addContentView(wv, lp)
                wv.loadDataWithBaseURL(base_url, html, 'text/html',
                                       'utf-8', None)
                self.wv = wv
            except Exception as e:
                Clock.schedule_once(
                    lambda dt: self.app.console_write(
                        'WebView error: %s\n' % e, 'err'), 0)

        def _destroy_now(self):
            if self.wv is not None:
                try:
                    parent = self.wv.getParent()
                    if parent is not None:
                        parent.removeView(self.wv)
                    self.wv.destroy()
                except Exception:
                    pass
                self.wv = None

        @run_on_ui_thread
        def _android_close(self):
            self._destroy_now()

        @run_on_ui_thread
        def _android_visible(self, vis):
            if self.wv is not None:
                self.wv.setVisibility(0 if vis else 4)

        @run_on_ui_thread
        def _android_eval(self, js):
            if self.wv is None:
                return
            cb = _JSCallback(self._on_logs)
            self._cbs.append(cb)
            self._cbs = self._cbs[-8:]
            self.wv.evaluateJavascript(js, cb)

    def _poll_logs(self, dt):
        if ANDROID and self.wv is not None:
            self._android_eval(
                "(function(){var l=window.__cl||[];window.__cl=[];"
                "return JSON.stringify(l)})()")

    def _on_logs(self, value):
        if not value or value == 'null':
            return
        try:
            data = json.loads(json.loads(value))
        except Exception:
            return
        if data:
            Clock.schedule_once(lambda dt: self.app.web_logs(data), 0)

    def reload(self):
        if self._last:
            self.show(*self._last)

    def set_visible(self, vis):
        if ANDROID:
            self._android_visible(vis)

    def close(self):
        self.open = False
        if self._poll:
            self._poll.cancel()
            self._poll = None
        if ANDROID:
            self._android_close()


# --------------------------------------------------------------------------
#  Documents and tabs
# --------------------------------------------------------------------------
class Doc:
    def __init__(self, path, text, name=None):
        self.path = path
        self.name = name or os.path.basename(path)
        self.lang = lang_of(self.name)[0]
        self.saved_text = text
        self.init_text = text
        self.dirty = False
        self.editor = None


class TabItem(BoxLayout):
    def __init__(self, doc, active, on_select, on_close, **kw):
        super().__init__(size_hint_x=None, width=dp(130), **kw)
        self.active = active
        label = ('* ' if doc.dirty else '') + doc.name
        self.btn = Btn(label, 'clear', radius=0, font_size=sp(12))
        self.btn.shorten = True
        self.btn.shorten_from = 'right'
        self.btn.bind(on_release=lambda *a: on_select(doc))
        self.x_btn = Btn('x', 'clear', radius=0, size_hint_x=None,
                         width=dp(30), font_size=sp(13))
        self.x_btn.bind(on_release=lambda *a: on_close(doc))
        self.add_widget(self.btn)
        self.add_widget(self.x_btn)
        with self.canvas.before:
            self._c = Color(0, 0, 0, 1)
            self._r = Rectangle()
        with self.canvas.after:
            self._ac = Color(0, 0, 0, 1)
            self._ar = Rectangle()
        self.bind(pos=self._upd, size=self._upd)
        self.apply_theme()

    def _upd(self, *a):
        self._r.pos = self.pos
        self._r.size = self.size
        self._ar.pos = self.pos
        self._ar.size = (self.width, dp(2) if self.active else 0)

    def apply_theme(self):
        self._c.rgba = THEME.c('bg' if self.active else 'bar')
        self._ac.rgba = THEME.c('accent')
        self.btn.color = THEME.c('text' if self.active else 'dim')
        self.x_btn.color = THEME.c('dim')
        self._upd()


# --------------------------------------------------------------------------
#  File browser
# --------------------------------------------------------------------------
def human_size(n):
    for u in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or u == 'GB':
            return ('%d %s' % (n, u)) if u == 'B' else '%.1f %s' % (n, u)
        n /= 1024.0


class Row(ListBtn):
    def __init__(self, text, on_tap, on_long, **kw):
        super().__init__(text=text, **kw)
        self._tap, self._long = on_tap, on_long
        self._lt = None
        self._fired = False
        self.bind(on_press=self._press, on_release=self._release)

    def _press(self, *a):
        self._fired = False
        self._lt = Clock.schedule_once(self._fire, .55)

    def _fire(self, dt):
        self._fired = True
        self._long()

    def _release(self, *a):
        if self._lt:
            self._lt.cancel()
        if not self._fired:
            self._tap()


class FileBrowser(Sheet):
    def __init__(self, app, start, mode='open', default_name='', on_pick=None):
        self.app = app
        self.mode = mode
        self.on_pick = on_pick
        self.path = start if os.path.isdir(start) else app.workspace
        body = BoxLayout(orientation='vertical', spacing=dp(6))
        nav = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(4))
        up = Btn('Up', 'flat', size_hint_x=None, width=dp(46))
        up.bind(on_release=lambda *a: self.go(os.path.dirname(self.path)))
        self.path_lbl = Txt('', 'dim', halign='left', valign='middle',
                            shorten=True, shorten_from='left',
                            font_size=sp(11))
        self.path_lbl.bind(size=lambda w, s: setattr(
            w, 'text_size', (w.width, w.height)))
        ws = Btn('Work', 'flat', size_hint_x=None, width=dp(50))
        ws.bind(on_release=lambda *a: self.go(app.workspace))
        nav.add_widget(up)
        nav.add_widget(self.path_lbl)
        nav.add_widget(ws)
        if ANDROID:
            sd = Btn('SD', 'flat', size_hint_x=None, width=dp(40))
            sd.bind(on_release=lambda *a: self.go('/storage/emulated/0'))
            nav.add_widget(sd)
        body.add_widget(nav)
        self.scroll = ScrollView(bar_width=dp(3))
        self.grid = BoxLayout(orientation='vertical', size_hint_y=None,
                              spacing=dp(3))
        self.grid.bind(minimum_height=self.grid.setter('height'))
        self.scroll.add_widget(self.grid)
        body.add_widget(self.scroll)
        self.name_in = None
        acts = []
        nf = Btn('New file', 'flat')
        nf.bind(on_release=lambda *a: self.new_item(False))
        nd = Btn('New folder', 'flat')
        nd.bind(on_release=lambda *a: self.new_item(True))
        acts += [nf, nd]
        body.add_widget(hrow(*acts))
        if mode == 'saveas':
            self.name_in = Field(text=default_name, hint_text='File name',
                                 font_size=sp(14))
            ok = Btn('Save', 'accent', size_hint_x=None, width=dp(70))
            ok.bind(on_release=lambda *a: self.confirm_name())
            body.add_widget(hrow(self.name_in, ok))
        hint = Txt('Tap to open  |  Long-press for rename / delete', 'dim',
                   size_hint_y=None, height=dp(16), font_size=sp(10))
        body.add_widget(hint)
        super().__init__('Save as' if mode == 'saveas' else 'Files', body)
        self.refresh()

    def go(self, p):
        if p and os.path.isdir(p):
            self.path = p
            self.refresh()
        else:
            self.app.toast('Cannot open that folder')

    def refresh(self):
        self.grid.clear_widgets()
        self.path_lbl.text = self.path
        try:
            entries = sorted(os.scandir(self.path), key=lambda e: (
                not e.is_dir(), e.name.lower()))
        except Exception as e:
            self.grid.add_widget(Txt('Cannot read folder: %s' % e, 'danger',
                                     size_hint_y=None, height=dp(40)))
            return
        shown = 0
        for e in entries:
            if e.name.startswith('.'):
                continue
            shown += 1
            if e.is_dir():
                txt = '[color=%s][b]%s/[/b][/color]' % (
                    THEME.hex('accent'), escape_markup(e.name))
            else:
                try:
                    sz = human_size(e.stat().st_size)
                except Exception:
                    sz = ''
                txt = '%s   [color=%s]%s[/color]' % (
                    escape_markup(e.name), THEME.hex('dim'), sz)
            r = Row(txt, lambda en=e: self.tap(en), lambda en=e: self.menu(en),
                    size_hint_y=None, height=dp(42))
            self.grid.add_widget(r)
        if not shown:
            self.grid.add_widget(Txt('(empty folder)', 'dim',
                                     size_hint_y=None, height=dp(40)))
        themed(self.grid)
        self.scroll.scroll_y = 1

    def tap(self, e):
        if e.is_dir():
            self.go(e.path)
        elif self.mode == 'saveas':
            self.name_in.text = e.name
        else:
            self.dismiss()
            if self.on_pick:
                self.on_pick(e.path)

    def confirm_name(self):
        name = (self.name_in.text or '').strip()
        if not name or '/' in name:
            self.app.toast('Enter a valid file name')
            return
        full = os.path.join(self.path, name)
        if os.path.exists(full):
            self.app.confirm('Overwrite?', '%s already exists.' % name,
                             lambda: self._finish(full), 'Overwrite')
        else:
            self._finish(full)

    def _finish(self, full):
        self.dismiss()
        if self.on_pick:
            self.on_pick(full)

    def new_item(self, folder):
        def make(name):
            name = name.strip()
            if not name or '/' in name:
                return self.app.toast('Invalid name')
            p = os.path.join(self.path, name)
            if os.path.exists(p):
                return self.app.toast('Already exists')
            try:
                if folder:
                    os.makedirs(p)
                else:
                    open(p, 'w', encoding='utf-8').close()
                self.refresh()
            except Exception as e:
                self.app.toast('Error: %s' % e)
        self.app.prompt('New folder' if folder else 'New file', '', make,
                        'Create')

    def menu(self, e):
        body = BoxLayout(orientation='vertical', spacing=dp(6))
        s = None

        def do(fn):
            def inner(*a):
                s.dismiss()
                fn()
            return inner
        ren = Btn('Rename', 'flat', size_hint_y=None, height=dp(44))
        ren.bind(on_release=do(lambda: self.rename(e)))
        dele = Btn('Delete', 'danger', size_hint_y=None, height=dp(44))
        dele.bind(on_release=do(lambda: self.delete(e)))
        body.add_widget(ren)
        body.add_widget(dele)
        body.add_widget(Widget())
        s = Sheet(e.name, body, size_hint=(.8, None), height=dp(210))
        s.open()

    def rename(self, e):
        def go(name):
            name = name.strip()
            if not name or '/' in name:
                return self.app.toast('Invalid name')
            new = os.path.join(os.path.dirname(e.path), name)
            if os.path.exists(new):
                return self.app.toast('Already exists')
            try:
                os.rename(e.path, new)
                self.app.on_renamed(e.path, new)
                self.refresh()
            except Exception as ex:
                self.app.toast('Error: %s' % ex)
        self.app.prompt('Rename', e.name, go, 'Rename')

    def delete(self, e):
        def go():
            try:
                if e.is_dir():
                    shutil.rmtree(e.path)
                else:
                    os.remove(e.path)
                self.app.on_deleted(e.path)
                self.refresh()
            except Exception as ex:
                self.app.toast('Error: %s' % ex)
        self.app.confirm('Delete?', 'Delete %s permanently?' % e.name, go,
                         'Delete', danger=True)


# --------------------------------------------------------------------------
#  Application
# --------------------------------------------------------------------------
DEFAULTS = {
    'theme': 'dark', 'font_size': 14, 'tab_size': 4, 'auto_indent': True,
    'auto_pair': True, 'line_numbers': True, 'autosave_run': True,
}

SYMBOLS = ['Tab', '{', '}', '(', ')', '[', ']', '<', '>', '/', '"', "'", '=',
           ';', ':', ',', '.', '_', '-', '+', '*', '&', '|', '!', '#', '$',
           '%', '\\', '`', '~', '=>']


class CodeForgeApp(App):
    title = 'CodeForge'

    # -- setup ------------------------------------------------------------
    def build(self):
        self.data_dir = self.user_data_dir
        self.workspace = os.path.join(self.data_dir, 'projects')
        os.makedirs(self.workspace, exist_ok=True)
        self.settings = dict(DEFAULTS)
        self._load_json('settings.json', self.settings)
        THEME.set(self.settings['theme'])
        Window.clearcolor = THEME.c('bg')
        if ANDROID:
            Window.softinput_mode = 'resize'
            try:
                from android.permissions import request_permissions, \
                    Permission
                request_permissions([Permission.READ_EXTERNAL_STORAGE,
                                     Permission.WRITE_EXTERNAL_STORAGE])
            except Exception:
                pass
        self.docs = []
        self.active = None
        self.runner = PyRunner(self)
        self.preview = Preview(self)
        self.find_state = {'case': False}
        self._exit_armed = 0

        self.root_fl = FloatLayout()
        self.main = BoxLayout(orientation='vertical')
        self.root_fl.add_widget(self.main)
        self._build_main()
        self._build_preview_layer()
        self.toast_lbl = None
        Window.bind(on_keyboard=self.on_key)
        self._seed_workspace()
        self._restore_session()
        if not self.docs:
            self.open_path(os.path.join(self.workspace, 'main.py'))
        Clock.schedule_once(lambda dt: self.apply_theme_all(), 0)
        return self.root_fl

    def _load_json(self, name, into):
        p = os.path.join(self.data_dir, name)
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(into, dict):
                into.update(data)
                return into
            return data
        except Exception:
            return into

    def _save_json(self, name, data):
        try:
            with open(os.path.join(self.data_dir, name), 'w',
                      encoding='utf-8') as f:
                json.dump(data, f)
        except Exception:
            pass

    def _seed_workspace(self):
        seeds = {
            'main.py': TEMPLATES['Python'][1],
            'script.js': TEMPLATES['JavaScript'][1],
            'index.html': TEMPLATES['HTML'][1],
        }
        flag = os.path.join(self.data_dir, '.seeded')
        if os.path.exists(flag):
            return
        for n, t in seeds.items():
            p = os.path.join(self.workspace, n)
            if not os.path.exists(p):
                with open(p, 'w', encoding='utf-8') as f:
                    f.write(t)
        open(flag, 'w').close()

    # -- main layout ------------------------------------------------------
    def _build_main(self):
        m = self.main
        top = Bar('bar', size_hint_y=None, height=dp(52),
                  padding=(dp(6), dp(6)), spacing=dp(4))
        self.top_bar = top
        self.run_btn = None
        spec = [('Files', 'flat', self.show_files, 1),
                ('New', 'flat', self.show_new, 1),
                ('Save', 'flat', lambda: self.save_active(), 1),
                ('Undo', 'flat', lambda: self.undo(), 1),
                ('Redo', 'flat', lambda: self.redo(), 1),
                ('RUN', 'accent', lambda: self.run_active(), 1.25),
                ('More', 'flat', self.show_more, 1)]
        for label, kind, fn, hint in spec:
            b = Btn(label, kind, size_hint_x=hint, font_size=sp(12),
                    bold=(label == 'RUN'))
            b.bind(on_release=lambda w, f=fn: f())
            top.add_widget(b)
            if label == 'RUN':
                self.run_btn = b
        m.add_widget(top)

        self.tab_scroll = ScrollView(size_hint_y=None, height=dp(38),
                                     do_scroll_y=False,
                                     bar_width=0)
        self.tab_box = BoxLayout(size_hint_x=None, spacing=dp(1))
        self.tab_box.bind(minimum_width=self.tab_box.setter('width'))
        self.tab_scroll.add_widget(self.tab_box)
        self.tab_bg = Bar('bar', size_hint_y=None, height=dp(38))
        self.tab_bg.add_widget(self.tab_scroll)
        m.add_widget(self.tab_bg)

        self._build_find_bar()
        m.add_widget(self.find_bar)

        self.editor_area = BoxLayout()
        self.gutter = Gutter()
        self.editor_holder = BoxLayout()
        self.editor_area.add_widget(self.gutter)
        self.editor_area.add_widget(self.editor_holder)
        m.add_widget(self.editor_area)

        self.console = Console(on_close=self.hide_console, size_hint_y=None,
                               height=0, opacity=0)
        m.add_widget(self.console)

        sym = Bar('bar', size_hint_y=None, height=dp(40),
                  padding=(dp(4), dp(3)))
        sv = ScrollView(do_scroll_y=False, bar_width=0)
        row = BoxLayout(size_hint_x=None, spacing=dp(4))
        row.bind(minimum_width=row.setter('width'))
        for s in SYMBOLS:
            w = dp(52) if s == 'Tab' else dp(38)
            b = Btn(s, 'flat', size_hint_x=None, width=w, radius=6,
                    font_name=MONO, font_size=sp(15))
            b.bind(on_release=lambda wd, ch=s: self.type_symbol(ch))
            row.add_widget(b)
        sv.add_widget(row)
        sym.add_widget(sv)
        self.sym_bar = sym
        m.add_widget(sym)

        st = Bar('panel', size_hint_y=None, height=dp(22),
                 padding=(dp(8), 0), spacing=dp(8))
        self.st_pos = Txt('Ln 1, Col 1', 'dim', halign='left',
                          valign='middle', font_size=sp(10))
        self.st_lang = Txt('', 'accent', halign='center', valign='middle',
                           font_size=sp(10))
        self.st_state = Txt('', 'dim', halign='right', valign='middle',
                            font_size=sp(10))
        for w in (self.st_pos, self.st_lang, self.st_state):
            w.bind(size=lambda wd, s: setattr(wd, 'text_size',
                                              (wd.width, wd.height)))
            st.add_widget(w)
        m.add_widget(st)

    def _build_find_bar(self):
        fb = Bar('bar', orientation='vertical', size_hint_y=None, height=0,
                 opacity=0, padding=(dp(6), dp(4)), spacing=dp(4))
        self.find_in = Field(hint_text='Find', font_size=sp(13))
        self.find_in.bind(text=lambda *a: self.update_find_count())
        self.find_in.bind(on_text_validate=lambda *a: self.find_step(1))
        self.rep_in = Field(hint_text='Replace with', font_size=sp(13))
        self.find_count = Txt('', 'dim', size_hint_x=None, width=dp(46),
                              font_size=sp(11))
        case = Btn('Aa', 'flat', size_hint_x=None, width=dp(38))
        case.bind(on_release=lambda w: self.toggle_case(w))
        self.case_btn = case
        prev = Btn('<', 'flat', size_hint_x=None, width=dp(38))
        prev.bind(on_release=lambda *a: self.find_step(-1))
        nxt = Btn('>', 'flat', size_hint_x=None, width=dp(38))
        nxt.bind(on_release=lambda *a: self.find_step(1))
        close = Btn('x', 'ghost', size_hint_x=None, width=dp(34))
        close.bind(on_release=lambda *a: self.toggle_find(False))
        r1 = BoxLayout(spacing=dp(4))
        for w in (self.find_in, self.find_count, case, prev, nxt, close):
            r1.add_widget(w)
        rep = Btn('Replace', 'flat', size_hint_x=None, width=dp(72))
        rep.bind(on_release=lambda *a: self.replace_one())
        repa = Btn('All', 'accent', size_hint_x=None, width=dp(50))
        repa.bind(on_release=lambda *a: self.replace_all())
        r2 = BoxLayout(spacing=dp(4))
        for w in (self.rep_in, rep, repa):
            r2.add_widget(w)
        fb.add_widget(r1)
        fb.add_widget(r2)
        self.find_bar = fb
        self.find_open = False

    def _build_preview_layer(self):
        pl = BoxLayout(orientation='vertical')
        bar = Bar('bar', size_hint_y=None, height=dp(52),
                  padding=(dp(6), dp(6)), spacing=dp(4))
        close = Btn('Close', 'danger', size_hint_x=None, width=dp(72))
        close.bind(on_release=lambda *a: self.close_preview())
        reload_b = Btn('Reload', 'flat', size_hint_x=None, width=dp(72))
        reload_b.bind(on_release=lambda *a: self.preview.reload())
        self.pv_title = Txt('Preview', 'text', bold=True, halign='left',
                            valign='middle', font_size=sp(13))
        self.pv_title.bind(size=lambda w, s: setattr(
            w, 'text_size', (w.width, w.height)))
        self.pv_console_btn = Btn('Console', 'flat', size_hint_x=None,
                                  width=dp(78))
        self.pv_console_btn.bind(on_release=lambda *a: self.pv_toggle())
        for w in (close, reload_b, self.pv_title, self.pv_console_btn):
            bar.add_widget(w)
        pl.add_widget(bar)
        self.pv_console = Console()
        body = Bar('panel')
        body.add_widget(self.pv_console)
        pl.add_widget(body)
        self.preview_layer = pl
        self.pv_bar = bar
        self.pv_console_shown = False

    # -- theme ------------------------------------------------------------
    def apply_theme_all(self):
        Window.clearcolor = THEME.c('bg')
        themed(self.root_fl)
        for d in self.docs:
            if d.editor:
                self._style_editor(d.editor)
        self.refresh_tabs()
        self.gutter._trig()

    def _style_editor(self, ed):
        ed.style = STYLE_DARK if THEME.name == 'dark' else STYLE_LIGHT
        ed.background_color = THEME.c('bg')
        ed.foreground_color = THEME.c('text')
        ed.cursor_color = THEME.c('cursor')
        ed.selection_color = THEME.c('sel')
        ed.font_size = sp(self.settings['font_size'])
        ed._hl_update()

    # -- docs / tabs ------------------------------------------------------
    def make_editor(self, doc):
        lex = lang_of(doc.name)[1]()
        ed = Editor(self, doc.lang, text=doc.init_text, lexer=lex,
                    font_name=MONO, background_normal='',
                    background_active='', padding=[dp(8)] * 4,
                    font_size=sp(self.settings['font_size']),
                    do_wrap=False, use_bubble=True, use_handles=True)
        self._style_editor(ed)
        ed.bind(text=lambda *a, d=doc: self._on_text(d))
        ed.bind(cursor=lambda *a: self.update_status())
        ed.bind(focus=lambda *a: None)
        doc.editor = ed
        return ed

    def _on_text(self, doc):
        was = doc.dirty
        doc.dirty = doc.editor.text != doc.saved_text
        if doc.dirty != was:
            self.refresh_tabs()
            self.update_status()
        if self.find_open:
            self.update_find_count()

    def open_path(self, path):
        path = os.path.abspath(path)
        for d in self.docs:
            if d.path == path:
                return self.activate(d)
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()
        except Exception as e:
            self.toast('Cannot open: %s' % e)
            return None
        d = Doc(path, text)
        self.docs.append(d)
        self.activate(d)
        return d

    def activate(self, doc):
        if doc.editor is None:
            self.make_editor(doc)
        self.active = doc
        self.editor_holder.clear_widgets()
        self.editor_holder.add_widget(doc.editor)
        self.gutter.attach(doc.editor)
        self.refresh_tabs()
        self.update_status()
        if self.find_open:
            self.update_find_count()
        Clock.schedule_once(lambda dt: self._scroll_tab_into_view(), .05)

    def _scroll_tab_into_view(self):
        try:
            idx = self.docs.index(self.active)
            total = max(1, len(self.docs))
            if self.tab_box.width > self.tab_scroll.width:
                self.tab_scroll.scroll_x = idx / max(1, total - 1)
        except Exception:
            pass

    def refresh_tabs(self):
        self.tab_box.clear_widgets()
        for d in self.docs:
            t = TabItem(d, d is self.active, self.activate, self.close_doc)
            self.tab_box.add_widget(t)
        themed(self.tab_box)

    def close_doc(self, doc, force=False):
        if doc.dirty and not force:
            def save_close():
                self.save_doc(doc)
                self.close_doc(doc, True)
            self.confirm('Unsaved changes',
                         '%s has unsaved changes.' % doc.name,
                         lambda: self.close_doc(doc, True), 'Discard',
                         danger=True, extra=('Save', save_close))
            return
        idx = self.docs.index(doc)
        self.docs.remove(doc)
        if self.active is doc:
            if self.docs:
                self.activate(self.docs[min(idx, len(self.docs) - 1)])
            else:
                self.active = None
                self.editor_holder.clear_widgets()
                self.refresh_tabs()
                self.update_status()
                p = os.path.join(self.workspace, 'main.py')
                if os.path.exists(p):
                    self.open_path(p)
        else:
            self.refresh_tabs()

    def on_renamed(self, old, new):
        for d in self.docs:
            if d.path == old or (d.path and d.path.startswith(old + os.sep)):
                d.path = new + d.path[len(old):]
                d.name = os.path.basename(d.path)
                d.lang = lang_of(d.name)[0]
                if d.editor:
                    d.editor.lang = d.lang
                    d.editor.lexer = lang_of(d.name)[1]()
        self.refresh_tabs()
        self.update_status()

    def on_deleted(self, path):
        for d in list(self.docs):
            if d.path == path or (d.path and d.path.startswith(path + os.sep)):
                self.close_doc(d, True)

    # -- saving -----------------------------------------------------------
    def save_doc(self, doc, quiet=False):
        try:
            with open(doc.path, 'w', encoding='utf-8') as f:
                f.write(doc.editor.text)
            doc.saved_text = doc.editor.text
            doc.dirty = False
            self.refresh_tabs()
            self.update_status()
            if not quiet:
                self.toast('Saved %s' % doc.name)
            return True
        except Exception as e:
            self.toast('Save failed: %s' % e)
            return False

    def save_active(self):
        if self.active:
            self.save_doc(self.active)

    def save_as(self):
        d = self.active
        if not d:
            return

        def pick(path):
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(d.editor.text)
            except Exception as e:
                return self.toast('Save failed: %s' % e)
            existing = [x for x in self.docs if x.path == path and x is not d]
            for x in existing:
                self.docs.remove(x)
            d.path = path
            d.name = os.path.basename(path)
            d.lang = lang_of(d.name)[0]
            d.editor.lang = d.lang
            d.editor.lexer = lang_of(d.name)[1]()
            d.saved_text = d.editor.text
            d.dirty = False
            self.refresh_tabs()
            self.update_status()
            self.toast('Saved as %s' % d.name)
        start = os.path.dirname(d.path) if d.path else self.workspace
        FileBrowser(self, start, 'saveas', d.name, pick).open()

    # -- status / editing -------------------------------------------------
    def update_status(self):
        d = self.active
        if not d or not d.editor:
            self.st_pos.text = ''
            self.st_lang.text = ''
            self.st_state.text = ''
            return
        ed = d.editor
        self.st_pos.text = 'Ln %d, Col %d' % (ed.cursor_row + 1,
                                             ed.cursor_col + 1)
        self.st_lang.text = d.lang
        self.st_state.text = ('Modified' if d.dirty else 'Saved') + \
            '  |  Spaces: %d' % self.settings['tab_size']

    def type_symbol(self, ch):
        ed = self.active.editor if self.active else None
        if not ed:
            return
        ed.type_text('\t' if ch == 'Tab' else ch)

    def undo(self):
        if self.active and self.active.editor:
            self.active.editor.do_undo()

    def redo(self):
        if self.active and self.active.editor:
            self.active.editor.do_redo()

    # -- find & replace ---------------------------------------------------
    def toggle_find(self, show=None):
        show = (not self.find_open) if show is None else show
        self.find_open = show
        self.find_bar.height = dp(92) if show else 0
        self.find_bar.opacity = 1 if show else 0
        if show:
            ed = self.active.editor if self.active else None
            if ed and ed.selection_text and '\n' not in ed.selection_text:
                self.find_in.text = ed.selection_text
            self.find_in.focus = True
            self.update_find_count()

    def toggle_case(self, w):
        self.find_state['case'] = not self.find_state['case']
        w.kind = 'accent' if self.find_state['case'] else 'flat'
        w.apply_theme()
        self.update_find_count()

    def _positions(self):
        needle = self.find_in.text
        if not needle or not self.active or not self.active.editor:
            return []
        text = self.active.editor.text
        if not self.find_state['case']:
            text, needle = text.lower(), needle.lower()
        pos, i = [], 0
        while True:
            i = text.find(needle, i)
            if i == -1 or len(pos) > 20000:
                break
            pos.append(i)
            i += max(1, len(needle))
        return pos

    def update_find_count(self):
        n = len(self._positions())
        self.find_count.text = ('%d' % n) if self.find_in.text else ''

    def find_step(self, direction):
        pos = self._positions()
        ed = self.active.editor if self.active else None
        if not pos or not ed:
            return self.toast('No matches')
        L = len(self.find_in.text)
        cur = ed.cursor_index()
        if direction > 0:
            nxt = next((p for p in pos if p >= cur and
                        not (ed.selection_text and p == min(
                            ed.selection_from, ed.selection_to) and
                            ed.selection_to != ed.selection_from)), pos[0])
            if ed.selection_text:
                end = max(ed.selection_from, ed.selection_to)
                nxt = next((p for p in pos if p >= end), pos[0])
        else:
            start = min(ed.selection_from, ed.selection_to) \
                if ed.selection_text else cur
            nxt = next((p for p in reversed(pos) if p < start), pos[-1])
        ed.cursor = ed.get_cursor_from_index(nxt + L)
        ed.select_text(nxt, nxt + L)
        Clock.schedule_once(lambda dt: ed._center_cursor(), 0)

    def replace_one(self):
        ed = self.active.editor if self.active else None
        if not ed:
            return
        L = len(self.find_in.text)
        sel = ed.selection_text
        if sel and (sel == self.find_in.text or (
                not self.find_state['case'] and
                sel.lower() == self.find_in.text.lower())):
            ed.delete_selection()
            ed.raw_insert(self.rep_in.text)
        self.find_step(1)

    def replace_all(self):
        ed = self.active.editor if self.active else None
        needle = self.find_in.text
        if not ed or not needle:
            return
        flags = 0 if self.find_state['case'] else re.I
        new, n = re.subn(re.escape(needle),
                         lambda m: self.rep_in.text, ed.text, flags=flags)
        if n:
            ed.select_all()
            ed.delete_selection()
            ed.raw_insert(new)
            ed.cursor = (0, 0)
            ed.select_text(0, 0)
        self.toast('Replaced %d occurrence%s' % (n, '' if n == 1 else 's'))
        self.update_find_count()

    # -- running ----------------------------------------------------------
    def set_running(self, running):
        b = self.run_btn
        b.text = 'STOP' if running else 'RUN'
        b.kind = 'danger' if running else 'accent'
        b.apply_theme()

    def run_active(self):
        if self.runner.running:
            return self.runner.stop()
        d = self.active
        if not d:
            return self.toast('Open a file first')
        if d.lang not in RUNNABLE:
            return self.toast('Cannot run %s files' % d.lang)
        if self.settings.get('autosave_run', True) and d.dirty and d.path:
            self.save_doc(d, quiet=True)
        ed = d.editor
        ed.focus = False
        text = ed.text
        if d.lang == 'Python':
            self.show_console()
            self.console.line('$ python %s' % d.name, 'info')
            cwd = os.path.dirname(d.path) if d.path else self.workspace
            self.runner.run(text, d.path or d.name, cwd)
        else:
            base = 'file://%s/' % os.path.dirname(d.path) if d.path \
                else 'https://localhost/'
            html = build_html(d.lang, text)
            self.pv_title.text = d.name
            self.pv_console.clear()
            self.pv_console.line('$ %s' % d.name, 'info')
            self.pv_console_shown = False
            self.pv_console_btn.text = 'Console'
            if self.preview_layer.parent is None:
                self.root_fl.add_widget(self.preview_layer)
            self.preview.show(html, base)

    def console_write(self, s, kind='out'):
        self.console.write(s, kind)

    def web_logs(self, items):
        kinds = {'error': 'err', 'warn': 'warn', 'info': 'info',
                 'debug': 'dim', 'log': 'out'}
        for k, msg in items:
            self.pv_console.line(msg, kinds.get(k, 'out'))
            self.console.line('[web] ' + msg, kinds.get(k, 'out'))
        if any(k == 'error' for k, m in items) and not self.pv_console_shown:
            self.pv_console_btn.text = 'Console *'

    def pv_toggle(self):
        self.pv_console_shown = not self.pv_console_shown
        self.preview.set_visible(not self.pv_console_shown)
        self.pv_console_btn.text = 'Page' if self.pv_console_shown \
            else 'Console'

    def close_preview(self):
        self.preview.close()
        if self.preview_layer.parent is not None:
            self.root_fl.remove_widget(self.preview_layer)

    def show_console(self):
        self.console.height = max(dp(150), Window.height * .3)
        self.console.opacity = 1

    def hide_console(self):
        self.console.height = 0
        self.console.opacity = 0

    def ask_input(self, prompt, cb):
        body = BoxLayout(orientation='vertical', spacing=dp(8))
        body.add_widget(Txt(prompt or 'Program is asking for input:', 'text',
                            halign='left', valign='middle',
                            font_size=sp(13)))
        body.children[0].bind(size=lambda w, s: setattr(
            w, 'text_size', (w.width, w.height)))
        f = Field(hint_text='Type here')
        body.add_widget(hrow(f))
        done = []

        def submit(*a):
            if not done:
                done.append(1)
                cb(f.text)
                s.dismiss()
        ok = Btn('Send', 'accent', size_hint_y=None, height=dp(44))
        ok.bind(on_release=submit)
        f.bind(on_text_validate=submit)
        body.add_widget(ok)
        s = Sheet('input()', body, size_hint=(.92, None), height=dp(230))
        s.auto_dismiss = False
        s.bind(on_dismiss=lambda *a: (submit() if not done else None))
        s.open()
        Clock.schedule_once(lambda dt: setattr(f, 'focus', True), .2)

    # -- dialogs ----------------------------------------------------------
    def toast(self, msg, secs=1.8):
        if self.toast_lbl is not None:
            self.root_fl.remove_widget(self.toast_lbl)
        lbl = Label(text=msg, size_hint=(None, None), font_size=sp(13),
                    color=THEME.c('accent_text'),
                    padding=(dp(14), dp(8)))
        lbl.texture_update()
        lbl.size = (lbl.texture_size[0] + dp(28), lbl.texture_size[1] + dp(16))
        lbl.pos_hint = {'center_x': .5}
        lbl.y = dp(96)
        with lbl.canvas.before:
            Color(*THEME.c('accent'))
            rr = RoundedRectangle(radius=[dp(18)])
        lbl.bind(pos=lambda w, p: setattr(rr, 'pos', p),
                 size=lambda w, s: setattr(rr, 'size', s))
        rr.pos, rr.size = lbl.pos, lbl.size
        self.toast_lbl = lbl
        self.root_fl.add_widget(lbl)

        def gone(dt):
            if self.toast_lbl is lbl:
                self.root_fl.remove_widget(lbl)
                self.toast_lbl = None
        Clock.schedule_once(gone, secs)

    def confirm(self, title, msg, on_yes, yes_text='OK', danger=False,
                extra=None):
        body = BoxLayout(orientation='vertical', spacing=dp(8))
        lbl = Txt(msg, 'text', halign='left', valign='top', font_size=sp(13))
        lbl.bind(size=lambda w, s: setattr(w, 'text_size', (w.width, None)))
        body.add_widget(lbl)
        s = None

        def yes(*a):
            s.dismiss()
            on_yes()
        no = Btn('Cancel', 'flat')
        no.bind(on_release=lambda *a: s.dismiss())
        ok = Btn(yes_text, 'danger' if danger else 'accent')
        ok.bind(on_release=yes)
        btns = [no]
        if extra:
            ex = Btn(extra[0], 'accent')

            def do_extra(*a):
                s.dismiss()
                extra[1]()
            ex.bind(on_release=do_extra)
            btns.append(ex)
        btns.append(ok)
        body.add_widget(hrow(*btns, h=dp(44)))
        s = Sheet(title, body, size_hint=(.9, None), height=dp(210))
        s.open()

    def prompt(self, title, default, on_ok, ok_text='OK'):
        body = BoxLayout(orientation='vertical', spacing=dp(8))
        f = Field(text=default)
        body.add_widget(hrow(f))
        s = None

        def go(*a):
            s.dismiss()
            on_ok(f.text)
        ok = Btn(ok_text, 'accent', size_hint_y=None, height=dp(44))
        ok.bind(on_release=go)
        f.bind(on_text_validate=go)
        body.add_widget(ok)
        body.add_widget(Widget())
        s = Sheet(title, body, size_hint=(.9, None), height=dp(210))
        s.open()
        Clock.schedule_once(lambda dt: setattr(f, 'focus', True), .2)

    # -- menus ------------------------------------------------------------
    def show_files(self):
        start = os.path.dirname(self.active.path) if self.active and \
            self.active.path else self.workspace
        FileBrowser(self, start, 'open', '', self.open_path).open()

    def show_new(self):
        body = BoxLayout(orientation='vertical', spacing=dp(8))
        name = Field(text='', hint_text='File name (e.g. app.py)')
        body.add_widget(hrow(name))
        body.add_widget(Txt('Pick a template (created in your workspace):',
                            'dim', size_hint_y=None, height=dp(22),
                            halign='left', valign='middle'))
        body.children[0].bind(size=lambda w, s: setattr(
            w, 'text_size', (w.width, w.height)))
        s = None

        def create(kind):
            default, content = TEMPLATES[kind]
            n = name.text.strip() or default
            if '/' in n:
                return self.toast('Invalid name')
            if not os.path.splitext(n)[1]:
                n += os.path.splitext(default)[1]
            p = os.path.join(self.workspace, n)
            base, ext = os.path.splitext(p)
            i = 1
            while os.path.exists(p):
                p = '%s_%d%s' % (base, i, ext)
                i += 1
            try:
                with open(p, 'w', encoding='utf-8') as f:
                    f.write(content)
            except Exception as e:
                return self.toast('Error: %s' % e)
            s.dismiss()
            self.open_path(p)
        for kind in ('Python', 'JavaScript', 'HTML', 'Blank'):
            b = Btn(kind, 'flat', size_hint_y=None, height=dp(44))
            b.bind(on_release=lambda w, k=kind: create(k))
            body.add_widget(b)
        body.add_widget(Widget())
        s = Sheet('New file', body, size_hint=(.9, None), height=dp(380))
        s.open()

    def show_more(self):
        d = self.active
        ed = d.editor if d else None
        items = [
            ('Find & replace', lambda: self.toggle_find(True)),
            ('Go to line', self.goto_dialog),
            ('Comment / uncomment line', lambda: ed and ed.toggle_comment()),
            ('Indent', lambda: ed and ed.indent_lines()),
            ('Outdent', lambda: ed and ed.indent_lines(True)),
            ('Duplicate line', lambda: ed and ed.duplicate_line()),
            ('Select all', lambda: ed and ed.select_all()),
            ('Save as...', self.save_as),
            ('Save all', self.save_all),
            ('Console', lambda: self.show_console() if
             self.console.opacity == 0 else self.hide_console()),
            ('Close tab', lambda: d and self.close_doc(d)),
            ('Settings', self.show_settings),
            ('About', self.show_about),
        ]
        grid = BoxLayout(orientation='vertical', size_hint_y=None,
                         spacing=dp(4))
        grid.bind(minimum_height=grid.setter('height'))
        sc = ScrollView(bar_width=dp(3))
        s = None

        def mk(fn):
            def go(*a):
                s.dismiss()
                Clock.schedule_once(lambda dt: fn(), .05)
            return go
        for label, fn in items:
            b = ListBtn(label, 'flat', size_hint_y=None, height=dp(44),
                        markup=False)
            b.bind(on_release=mk(fn))
            grid.add_widget(b)
        sc.add_widget(grid)
        s = Sheet('Menu', sc, size_hint=(.82, .8))
        s.open()

    def goto_dialog(self):
        ed = self.active.editor if self.active else None
        if not ed:
            return
        self.prompt('Go to line (1-%d)' % len(ed._lines), '',
                    lambda v: v.strip().isdigit() and ed.goto_line(
                        int(v.strip())), 'Go')

    def save_all(self):
        n = 0
        for d in self.docs:
            if d.dirty and self.save_doc(d, quiet=True):
                n += 1
        self.toast('Saved %d file%s' % (n, '' if n == 1 else 's'))

    def show_about(self):
        body = BoxLayout(orientation='vertical', spacing=dp(6))
        t = Txt('CodeForge %s\n\nPython, JavaScript and HTML editor.\n'
                'Runs on 32-bit (armeabi-v7a) and 64-bit (arm64-v8a) '
                'Android.\n\nWorkspace:\n%s' % (APP_VERSION, self.workspace),
                'text', halign='left', valign='top', font_size=sp(13))
        t.bind(size=lambda w, s: setattr(w, 'text_size', (w.width, None)))
        body.add_widget(t)
        Sheet('About', body, size_hint=(.9, None), height=dp(300)).open()

    def show_settings(self):
        st = self.settings
        body = BoxLayout(orientation='vertical', spacing=dp(8),
                         size_hint_y=None)
        body.bind(minimum_height=body.setter('height'))
        sc = ScrollView(bar_width=dp(3))

        def seg(label, options, key, cast=lambda x: x, after=None):
            body.add_widget(Txt(label, 'dim', size_hint_y=None,
                                height=dp(20), halign='left',
                                valign='middle'))
            body.children[0].bind(size=lambda w, s: setattr(
                w, 'text_size', (w.width, w.height)))
            btns = []

            def pick(val):
                st[key] = cast(val)
                for b, v in btns:
                    b.kind = 'accent' if cast(v) == st[key] else 'flat'
                    b.apply_theme()
                if after:
                    after()
                self._save_json('settings.json', st)
            row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
            for text, val in options:
                b = Btn(text, 'accent' if cast(val) == st[key] else 'flat')
                b.bind(on_release=lambda w, v=val: pick(v))
                btns.append((b, val))
                row.add_widget(b)
            body.add_widget(row)

        def set_theme():
            THEME.set(st['theme'])
            self.apply_theme_all()

        def set_font():
            for d in self.docs:
                if d.editor:
                    d.editor.font_size = sp(st['font_size'])
            self.gutter._trig()

        seg('Theme', [('Dark', 'dark'), ('Light', 'light')], 'theme',
            after=set_theme)
        seg('Tab size', [('2', 2), ('4', 4), ('8', 8)], 'tab_size', int,
            after=self.update_status)
        seg('Auto-indent', [('On', 1), ('Off', 0)], 'auto_indent',
            lambda x: bool(int(x)))
        seg('Auto-close brackets, quotes, tags',
            [('On', 1), ('Off', 0)], 'auto_pair', lambda x: bool(int(x)))
        seg('Line numbers', [('Show', 1), ('Hide', 0)], 'line_numbers',
            lambda x: bool(int(x)), after=lambda: self.gutter._trig())
        seg('Save automatically before running', [('On', 1), ('Off', 0)],
            'autosave_run', lambda x: bool(int(x)))
        body.add_widget(Txt('Font size: %d' % st['font_size'], 'dim',
                            size_hint_y=None, height=dp(20), halign='left',
                            valign='middle'))
        lab = body.children[0]
        lab.bind(size=lambda w, s: setattr(w, 'text_size', (w.width,
                                                           w.height)))
        sl = Slider(min=10, max=28, step=1, value=st['font_size'],
                    size_hint_y=None, height=dp(36))

        def on_slide(w, v):
            st['font_size'] = int(v)
            lab.text = 'Font size: %d' % int(v)
            set_font()
            self._save_json('settings.json', st)
        sl.bind(value=on_slide)
        body.add_widget(sl)
        if ANDROID:
            ga = Btn('Grant all-files access (to edit files outside the '
                     'app)', 'flat', size_hint_y=None, height=dp(44),
                     font_size=sp(12))
            ga.bind(on_release=lambda *a: self.grant_storage())
            body.add_widget(ga)
        sc.add_widget(body)
        s = Sheet('Settings', sc, size_hint=(.92, .85))
        s.open()

    def grant_storage(self):
        try:
            act = autoclass('org.kivy.android.PythonActivity').mActivity
            Intent = autoclass('android.content.Intent')
            Settings = autoclass('android.provider.Settings')
            Uri = autoclass('android.net.Uri')
            ver = autoclass('android.os.Build$VERSION').SDK_INT
            if ver >= 30:
                it = Intent(
                    Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                    Uri.parse('package:' + act.getPackageName()))
                act.startActivity(it)
            else:
                self.toast('Storage permission was requested at startup')
        except Exception as e:
            self.toast('Could not open settings: %s' % e)

    # -- session ----------------------------------------------------------
    def _restore_session(self):
        data = self._load_json('session.json', {})
        if not isinstance(data, dict):
            return
        for item in data.get('docs', []):
            p = item.get('path')
            if not p or not os.path.exists(p):
                continue
            d = self.open_path(p)
            if d is not None and item.get('draft') is not None:
                d.editor.text = item['draft']
        act = data.get('active')
        for d in self.docs:
            if d.path == act:
                self.activate(d)

    def _save_session(self):
        docs = []
        for d in self.docs:
            if not d.path:
                continue
            rec = {'path': d.path}
            if d.dirty and d.editor:
                rec['draft'] = d.editor.text
            docs.append(rec)
        self._save_json('session.json', {
            'docs': docs, 'active': self.active.path if self.active else None})
        self._save_json('settings.json', self.settings)

    def on_pause(self):
        self._save_session()
        return True

    def on_resume(self):
        pass

    def on_stop(self):
        self._save_session()
        self.preview.close()

    # -- keys -------------------------------------------------------------
    def on_key(self, window, key, *args):
        if key != 27:
            return False
        if self.preview_layer.parent is not None:
            self.close_preview()
            return True
        # close any open modal first
        for w in Window.children[:]:
            if isinstance(w, ModalView):
                w.dismiss()
                return True
        if self.active and self.active.editor and self.active.editor.focus:
            self.active.editor.focus = False
            return True
        if self.find_open:
            self.toggle_find(False)
            return True
        now = time.time()
        if any(d.dirty for d in self.docs) and now - self._exit_armed > 2:
            self._exit_armed = now
            self.toast('Unsaved changes - press back again to exit')
            return True
        self._save_session()
        return False


if __name__ == '__main__':
    CodeForgeApp().run()
