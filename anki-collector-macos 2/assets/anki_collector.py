#!/usr/bin/env python3
"""Free, offline English->Chinese Anki collector for macOS."""
import base64
import hashlib
import html
import os
import re
import subprocess
import tempfile
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from urllib import request
import json
from pathlib import Path

DECK = '英语学习积累'
ANKI_URL = 'http://127.0.0.1:8765'


def anki(action, **params):
    payload = json.dumps({'action': action, 'version': 6, 'params': params}, ensure_ascii=False).encode('utf-8')
    req = request.Request(ANKI_URL, data=payload, headers={'Content-Type': 'application/json'})
    with request.urlopen(req, timeout=25) as response:
        result = json.load(response)
    if result.get('error'):
        raise RuntimeError(str(result['error']))
    return result['result']


def choose_model():
    names = anki('modelNames')
    for name in names:
        fields = anki('modelFieldNames', modelName=name)
        if '正面' in fields and '背面' in fields:
            return name
    raise RuntimeError('Anki 中找不到同时具有「正面」「背面」字段的笔记类型。')


def make_audio(sentence, filename):
    # 'say' produces lossless audio, then afconvert converts it to widely-supported AAC/M4A.
    with tempfile.TemporaryDirectory(prefix='anki_sentence_') as tmp:
        aiff = str(Path(tmp) / 'speech.aiff')
        m4a = str(Path(tmp) / 'speech.m4a')
        subprocess.run(['say', '-v', 'Samantha', '-o', aiff, sentence], check=True, capture_output=True, text=True)
        subprocess.run(['afconvert', '-f', 'm4af', '-d', 'aac', aiff, m4a], check=True, capture_output=True, text=True)
        data = base64.b64encode(Path(m4a).read_bytes()).decode('ascii')
    anki('storeMediaFile', filename=filename, data=data)


def get_translation(sentence):
    os.environ['ARGOS_CHUNK_TYPE'] = 'SPACY'
    os.environ['ARGOS_DEVICE_TYPE'] = 'cpu'
    import argostranslate.translate
    result = argostranslate.translate.translate(sentence, 'en', 'zh')
    if not result or not result.strip():
        raise RuntimeError('翻译结果为空，请检查离线模型。')
    return result.strip()


class Collector(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Anki 英语句子收集器')
        self.geometry('660x540')
        self.minsize(540, 460)
        self.sentence_version = 0
        self.translation_version = -1
        self.busy = False
        self.status_var = tk.StringVar(value='请粘贴英文句子，然后点击「翻译」。')
        self.deck_var = tk.StringVar(value='目标牌组：' + DECK)
        pad = {'padx': 16}
        ttk.Label(self, text='英文原句', font=('', 13, 'bold')).pack(anchor='w', pady=(16, 4), **pad)
        self.english = tk.Text(self, height=5, wrap='word', font=('', 13), undo=True)
        self.english.pack(fill='both', expand=True, **pad)
        self.english.bind('<<Modified>>', self.on_english_modified)
        toolbar = ttk.Frame(self)
        toolbar.pack(fill='x', pady=8, **pad)
        self.translate_btn = ttk.Button(toolbar, text='翻译成中文', command=self.translate)
        self.translate_btn.pack(side='left')
        ttk.Button(toolbar, text='粘贴', command=self.paste).pack(side='left', padx=(8, 0))
        self.listen_btn = ttk.Button(toolbar, text='试听英语', command=self.listen)
        self.listen_btn.pack(side='left', padx=(8, 0))
        ttk.Label(self, text='中文翻译（可编辑）', font=('', 13, 'bold')).pack(anchor='w', pady=(4, 4), **pad)
        self.chinese = tk.Text(self, height=5, wrap='word', font=('', 13), undo=True)
        self.chinese.pack(fill='both', expand=True, **pad)
        ttk.Label(self, textvariable=self.deck_var).pack(anchor='w', pady=(12, 3), **pad)
        self.add_btn = ttk.Button(self, text='确认添加到 Anki', command=self.add)
        self.add_btn.pack(fill='x', padx=16, pady=(4, 10))
        ttk.Label(self, textvariable=self.status_var, wraplength=610, foreground='#555').pack(anchor='w', padx=16, pady=(0, 12))
        self.english.focus_set()

    def on_english_modified(self, _event):
        if self.english.edit_modified():
            self.sentence_version += 1
            self.english.edit_modified(False)

    def english_text(self):
        return self.english.get('1.0', 'end-1c').strip()

    def chinese_text(self):
        return self.chinese.get('1.0', 'end-1c').strip()

    def paste(self):
        try:
            clip = self.clipboard_get()
            self.english.delete('1.0', 'end')
            self.english.insert('1.0', clip)
        except tk.TclError:
            messagebox.showwarning('无法粘贴', '剪贴板没有可用的文字。')

    def work(self, operation, on_success):
        if self.busy:
            return
        self.busy = True
        self.translate_btn.configure(state='disabled')
        self.add_btn.configure(state='disabled')
        self.listen_btn.configure(state='disabled')

        def runner():
            try:
                value = operation()
                self.after(0, lambda: finish(value, None))
            except Exception as ex:
                self.after(0, lambda err=str(ex): finish(None, err))

        def finish(value, error):
            self.busy = False
            self.translate_btn.configure(state='normal')
            self.add_btn.configure(state='normal')
            self.listen_btn.configure(state='normal')
            if error:
                self.status_var.set('操作失败：' + error)
                messagebox.showerror('操作失败', error)
            else:
                on_success(value)

        threading.Thread(target=runner, daemon=True).start()

    def translate(self):
        text = self.english_text()
        if not text:
            messagebox.showwarning('缺少英文', '请先粘贴英文句子。')
            return
        version = self.sentence_version
        self.status_var.set('正在运行本地翻译（首次加载可能稍慢）...')

        def done(translated):
            if version != self.sentence_version:
                self.status_var.set('英文已被修改，旧翻译未覆盖。请重新翻译。')
                return
            self.chinese.delete('1.0', 'end')
            self.chinese.insert('1.0', translated)
            self.translation_version = version
            self.status_var.set('翻译完成。请检查中文，可修改后再确认添加。')

        self.work(lambda: get_translation(text), done)

    def listen(self):
        sentence = self.english_text()
        if not sentence:
            messagebox.showwarning('缺少英文', '请先粘贴英文句子。')
            return
        self.status_var.set('正在试听 Mac 英语语音...')
        self.work(lambda: subprocess.run(['say', '-v', 'Samantha', sentence], check=True, capture_output=True, text=True), lambda _res: self.status_var.set('试听完成。'))

    def add(self):
        english = self.english_text()
        chinese = self.chinese_text()
        if not english or not chinese:
            messagebox.showwarning('内容不完整', '需要同时填写英文和中文。')
            return
        if not messagebox.askyesno('确认添加', f'将这张卡片添加到「{DECK}」？\n\n正面：{chinese[:120]}\n\n背面：{english[:120]}'):
            return
        self.status_var.set('正在检查重复、生成语音并写入 Anki...')

        def operation():
            decks = anki('deckNames')
            if DECK not in decks:
                raise RuntimeError(f'找不到牌组「{DECK}」。请先在 Anki 中创建。')
            model = choose_model()
            digest = hashlib.sha256(english.casefold().strip().encode('utf-8')).hexdigest()[:20]
            tag = 'en_collector_' + digest
            # Exact dedup for cards made by this collector.
            matches = anki('findNotes', query='tag:' + tag)
            if matches:
                return ('duplicate', matches[0])
            filename = f'anki_en_{digest}.m4a'
            make_audio(english, filename)
            back = html.escape(english).replace('\n', '<br>') + f'<br>[sound:{filename}]'
            note = {
                'deckName': DECK,
                'modelName': model,
                'fields': {'正面': html.escape(chinese).replace('\n', '<br>'), '背面': back},
                'tags': ['en_collector', tag],
                'options': {'allowDuplicate': False},
            }
            note_id = anki('addNote', note=note)
            return ('added', note_id)

        def done(value):
            result, note_id = value
            if result == 'duplicate':
                self.status_var.set(f'这条英文之前已通过收集器添加过（笔记编号 {note_id}）。')
                messagebox.showinfo('重复句子', '这句英文之前已经添加过，没有再次创建。')
            else:
                self.status_var.set(f'添加成功，笔记编号：{note_id}。可打开 Anki 查看。')
                messagebox.showinfo('添加成功', f'已写入「{DECK}」。\n笔记编号：{note_id}\n\n如需在手机上查看，请使用 Anki 同步。')

        self.work(operation, done)


if __name__ == '__main__':
    Collector().mainloop()
