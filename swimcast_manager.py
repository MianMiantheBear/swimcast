"""SwimCast desktop interface; translations live in locales.py."""
import json
import os
import queue
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import engine
from engine import AUDIO_PROCESSING, audio_filter, atempo_filter, convert_audio
from locales import EN, LOG_MESSAGES

APP_DIR = Path(os.path.abspath(__file__)).parent
SPEEDS = ['1.0', '1.25', '1.5', '1.75', '2.0', '2.25', '2.5']
GAINS = ['0', '3', '6', '9', '12']


def preset_name(values):
    """Derive the visible preset from saved processing values."""
    selected = dict(AUDIO_PROCESSING, **values)
    if all(selected[key] == value for key, value in AUDIO_PROCESSING.items()):
        return '游泳增强'
    speed_only = dict(AUDIO_PROCESSING, gain_db=0, limiter_enabled=False)
    if all(selected[key] == value for key, value in speed_only.items()):
        return '仅倍速'
    return '自定义'


class App:
    def __init__(self, root):
        self.root = root
        self.config_path = APP_DIR / 'podcast_config.json'
        self.settings_path = APP_DIR / 'settings.json'
        self.history_path = APP_DIR / 'download_history.json'
        self.config = engine.load_json(self.config_path, {'podcasts': []})
        self.settings = engine.load_json(self.settings_path, {
            'output_dir': str(APP_DIR / 'SwimCast_Output'), 'language': 'zh',
            'player_dir': '', 'audio': dict(AUDIO_PROCESSING), 'keep_originals': True,
        })
        self.language = self.settings.get('language', 'zh')
        self.events = queue.Queue()
        self.running = False
        self.control = None
        self.closing = False
        self.root.title('SwimCast Manager 3.0')
        self.root.geometry('1100x830')
        self.root.minsize(900, 600)
        self.build_ui()
        self.root.after(100, self.pump)
        self.root.protocol('WM_DELETE_WINDOW', self.close)

    def tr(self, text):
        return EN.get(text, text) if self.language == 'en' else text

    def log(self, key, *args):
        self.events.put(('log', key, args))

    def status(self, key):
        self.events.put(('status', key))

    def render_log(self, key, args):
        pair = LOG_MESSAGES.get(key)
        template = pair[1 if self.language == 'en' else 0] if pair else key
        try:
            return template.format(*args)
        except (IndexError, ValueError):
            return template + ' ' + str(args)

    def pump(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == 'log':
                    self.log_box.configure(state='normal')
                    self.log_box.insert('end', self.render_log(event[1], event[2]) + '\n')
                    self.log_box.see('end')
                    self.log_box.configure(state='disabled')
                elif event[0] == 'status':
                    self.status_var.set(self.render_log(event[1], ()))
                elif event[0] == 'ask':
                    _, prompt, answer, ready = event
                    answer.append(False if self.closing or self.control.stop_event.is_set() else
                                  messagebox.askyesno(self.tr('替换文件'), prompt, parent=self.root))
                    ready.set()
                elif event[0] == 'done':
                    self.running = False
                    for widget in self.task_buttons:
                        widget.configure(state='normal')
                    self.language_widget.configure(state='readonly')
                    self.pause_button.configure(state='disabled', text=self.tr('暂停'))
                    self.stop_button.configure(state='disabled')
                    self.refresh_library()
                    result = event[1]
                    self.status_var.set(self.render_log('stopped' if result.get('stopped') else 'finished', ()))
                    if self.closing:
                        self.root.destroy()
                        return
                    messagebox.showinfo(self.tr('任务结果'), self.render_log('summary', (
                        result.get('success', 0), result.get('skipped', 0), result.get('failed', 0))), parent=self.root)
        except queue.Empty:
            pass
        self.root.after(100, self.pump)

    def build_ui(self):
        for widget in self.root.winfo_children():
            widget.destroy()
        self.task_buttons = []
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill='both', expand=True)
        top = ttk.Frame(main)
        top.pack(fill='x')
        ttk.Label(top, text='SwimCast Manager 3.0', font=('Segoe UI', 17, 'bold')).pack(side='left')
        ttk.Label(top, text='语言 / Language').pack(side='right', padx=8)
        language = ttk.Combobox(top, values=['简体中文', 'English'], state='readonly', width=12)
        language.set('English' if self.language == 'en' else '简体中文')
        language.pack(side='right')
        language.bind('<<ComboboxSelected>>', lambda event: self.change_language(language.get()))
        self.language_widget = language
        panes = ttk.PanedWindow(main, orient='vertical')
        panes.pack(fill='both', expand=True, pady=10)
        notebook = ttk.Notebook(panes)
        panes.add(notebook, weight=4)
        programs = ttk.Frame(notebook, padding=8)
        library = ttk.Frame(notebook, padding=8)
        settings = ttk.Frame(notebook, padding=8)
        notebook.add(programs, text=self.tr('节目'))
        notebook.add(library, text=self.tr('音频库与传输'))
        notebook.add(settings, text=self.tr('设置'))
        self.tree = ttk.Treeview(programs, columns=('name', 'speed', 'gain', 'effects', 'source', 'count', 'rss'), show='headings', selectmode='extended')
        for column, title, width in [('name', '节目名称', 150), ('speed', '倍速', 60), ('gain', '增益', 80),
                                     ('effects', '其它音频处理', 260), ('source', '设置来源', 95),
                                     ('count', '检查最新集数', 110), ('rss', 'RSS 地址', 330)]:
            self.tree.heading(column, text=self.tr(title))
            self.tree.column(column, width=width, stretch=column in ('name', 'rss'))
        self.tree.pack(fill='both', expand=True)
        tree_scroll = ttk.Scrollbar(programs, orient='horizontal', command=self.tree.xview)
        self.tree.configure(xscrollcommand=tree_scroll.set)
        tree_scroll.pack(fill='x')
        self.tree.bind('<Double-1>', lambda event: self.edit())
        row = ttk.Frame(programs)
        row.pack(fill='x', pady=8)
        for text, command in [('添加节目', self.add), ('编辑节目', self.edit), ('删除节目', self.delete),
                              ('更新全部节目', self.update_all), ('更新所选节目', self.update_selected)]:
            self.button(row, text, command)
        ttk.Label(programs, text=self.tr('设置页修改所有未单独设置的节目；双击节目名称可为该节目单独设置倍速和音频处理。')).pack(anchor='w')
        ttk.Label(programs, text=self.tr('检查最新集数决定每次检查的范围；已下载节目默认跳过。')).pack(anchor='w')
        self.library_tree = ttk.Treeview(library, columns=('podcast', 'title', 'duration', 'verified', 'exists'), show='headings', selectmode='extended')
        for column, title, width in [('podcast', '节目名称', 150), ('title', '单集标题', 430), ('duration', '时长', 90), ('verified', '完整性状态', 145), ('exists', '本地文件', 100)]:
            self.library_tree.heading(column, text=self.tr(title))
            self.library_tree.column(column, width=width, stretch=column == 'title')
        scrollbar = ttk.Scrollbar(library, orient='vertical', command=self.library_tree.yview)
        self.library_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.library_tree.pack(fill='both', expand=True)
        row = ttk.Frame(library)
        row.pack(fill='x', pady=8)
        for text, command in [('刷新列表', self.refresh_library),
                              ('重新下载', self.redownload_selected), ('重新处理', self.reprocess_selected),
                              ('传输到播放器', self.transfer_selected), ('打开下载文件夹', self.open_output),
                              ('短片段 A/B 试听', self.audition)]:
            self.button(row, text, command)
        ttk.Label(library, text=self.tr('按 Ctrl 或 Shift 多选。重新处理优先使用保留原音，没有原音则重新下载。')).pack(anchor='w')
        self.output_var = tk.StringVar(value=self.settings.get('output_dir', str(APP_DIR / 'SwimCast_Output')))
        self.player_var = tk.StringVar(value=self.settings.get('player_dir', ''))
        footer = ttk.Frame(settings)
        footer.pack(side='bottom', fill='x', pady=(8, 0))
        self.button(footer, '保存设置', self.save_audio)
        scroll_host = ttk.Frame(settings)
        scroll_host.pack(side='top', fill='both', expand=True)
        canvas = tk.Canvas(scroll_host, highlightthickness=0)
        scroll = ttk.Scrollbar(scroll_host, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        content = ttk.Frame(canvas, padding=(0, 0, 8, 0))
        content_id = canvas.create_window((0, 0), window=content, anchor='nw')
        content.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(content_id, width=event.width))
        def scroll_settings(event):
            if notebook.select() != str(settings):
                return
            pointer = self.root.winfo_containing(event.x_root, event.y_root)
            if pointer is None or not (canvas.winfo_rootx() <= event.x_root < canvas.winfo_rootx() + canvas.winfo_width()
                                       and canvas.winfo_rooty() <= event.y_root < canvas.winfo_rooty() + canvas.winfo_height()):
                return
            canvas.yview_scroll(-int(event.delta / 120), 'units')
        self.root.bind_all('<MouseWheel>', scroll_settings)
        files = ttk.LabelFrame(content, text=self.tr('文件与传输'), padding=8)
        files.pack(fill='x', pady=(0, 8))
        ttk.Label(files, text=self.tr('先下载音频，再到“音频库与传输”页选择单集，复制或移动到播放器。'), wraplength=850).pack(anchor='w', pady=(0, 6))
        for label, variable, chooser in [('下载文件夹', self.output_var, self.choose_output), ('播放器文件夹', self.player_var, self.choose_player)]:
            row = ttk.LabelFrame(files, text=self.tr(label), padding=8)
            row.pack(fill='x', pady=4)
            ttk.Entry(row, textvariable=variable).pack(side='left', fill='x', expand=True)
            self.button(row, '选择…', chooser)
        self.transfer_mode_var = tk.StringVar(value=self.settings.get('transfer_mode', 'copy'))
        mode_row = ttk.Frame(files)
        mode_row.pack(fill='x', pady=3)
        ttk.Label(mode_row, text=self.tr('传输方式：')).pack(side='left')
        for value, label in [('copy', '复制（保留下载文件）'), ('move', '移动（校验后删除下载文件）')]:
            ttk.Radiobutton(mode_row, text=self.tr(label), value=value, variable=self.transfer_mode_var,
                            command=self.save).pack(side='left', padx=8)
        ttk.Label(files, text=self.tr('音频文件直接放入播放器文件夹，不建立节目子文件夹。'), wraplength=850).pack(anchor='w')
        self.keep_var = tk.BooleanVar(value=self.settings.get('keep_originals', True))
        ttk.Checkbutton(files, text=self.tr('保留原音，便于重新处理（会占用额外磁盘空间）'), variable=self.keep_var, command=self.save).pack(anchor='w', pady=6)
        audio_section = ttk.LabelFrame(content, text=self.tr('音频处理'), padding=8)
        audio_section.pack(fill='x')
        ttk.Label(audio_section, text=self.tr('适用于未单独设置的节目；双击节目名称可单独调整。'), wraplength=850).pack(anchor='w', pady=(0, 4))
        self.audio_panel(audio_section, self.settings.get('audio') or AUDIO_PROCESSING)
        log_panel = ttk.Frame(panes)
        panes.add(log_panel, weight=1)
        controls = ttk.Frame(log_panel)
        controls.pack(fill='x')
        self.pause_button = ttk.Button(controls, text=self.tr('暂停'), command=self.toggle_pause, state='disabled')
        self.pause_button.pack(side='left')
        self.stop_button = ttk.Button(controls, text=self.tr('停止任务'), command=self.stop, state='disabled')
        self.stop_button.pack(side='left', padx=6)
        self.status_var = tk.StringVar(value=self.tr('就绪'))
        ttk.Label(controls, textvariable=self.status_var).pack(side='left', padx=10)
        ttk.Label(log_panel, text=self.tr('运行日志（拖动上方分隔线可调整高度）')).pack(anchor='w', pady=(8, 2))
        self.log_box = tk.Text(log_panel, height=8, state='disabled', wrap='word')
        self.log_box.pack(fill='both', expand=True)
        self.root.after_idle(lambda: panes.sashpos(0, max(350, int(panes.winfo_height() * .72))) if panes.winfo_exists() else None)
        self.refresh_programs()
        self.refresh_library()

    def button(self, parent, text, command):
        widget = ttk.Button(parent, text=self.tr(text), command=command)
        widget.pack(side='left', padx=(0, 6), pady=3)
        self.task_buttons.append(widget)
        return widget

    def change_language(self, value):
        if self.running:
            return
        self.settings['audio'] = self.read_audio(self.global_audio)
        self.save()
        self.language = 'en' if value == 'English' else 'zh'
        self.settings['language'] = self.language
        engine.save_json(self.settings_path, self.settings)
        self.build_ui()

    def audio_panel(self, parent, values, global_panel=True):
        frame = ttk.LabelFrame(parent, text=self.tr('音频处理'), padding=8)
        frame.pack(fill='x', pady=6)
        variables = {
            'gain_db': tk.StringVar(value='%g' % values.get('gain_db', 9)),
            'limiter_enabled': tk.BooleanVar(value=values.get('limiter_enabled', True)),
            'normalization_enabled': tk.BooleanVar(value=values.get('normalization_enabled', False)),
            'compression_enabled': tk.BooleanVar(value=values.get('compression_enabled', False)),
        }
        presets = [self.tr('仅倍速'), self.tr('游泳增强'), self.tr('自定义')]
        preset = ttk.Combobox(frame, values=presets, state='readonly', width=20)
        preset.set(self.tr(preset_name(values)))
        preset.grid(row=0, column=0, sticky='w', pady=4)
        preset_tip = tk.StringVar()
        ttk.Label(frame, textvariable=preset_tip, wraplength=650).grid(row=0, column=1, columnspan=2, sticky='w', padx=8)
        def apply_preset(event=None):
            if preset.get() == self.tr('自定义'):
                set_advanced_state()
                return
            swimming = preset.get() == self.tr('游泳增强')
            variables['gain_db'].set('9' if swimming else '0')
            variables['limiter_enabled'].set(swimming)
            variables['normalization_enabled'].set(False)
            variables['compression_enabled'].set(False)
            for key, variable in advanced_vars.items():
                variable.set(str(AUDIO_PROCESSING[key]))
            preset.set(self.tr('游泳增强' if swimming else '仅倍速'))
            set_advanced_state()
        preset.bind('<<ComboboxSelected>>', apply_preset)
        ttk.Label(frame, text=self.tr('增益')).grid(row=1, column=0, sticky='w')
        ttk.Combobox(frame, textvariable=variables['gain_db'], values=GAINS, state='readonly', width=8).grid(row=1, column=1, sticky='w')
        ttk.Label(frame, text=self.tr('dB：0 表示关闭；数值越大，整体放大越多。')).grid(row=1, column=2, sticky='w', padx=8)
        for row, key, label, help_text in [
            (2, 'limiter_enabled', '峰值限制', '控制突然的大音量，降低削波风险；较响片段的实际增幅可能更小。'),
            (3, 'normalization_enabled', '响度标准化', '让不同节目音量更接近；其后还会叠加所选增益。'),
            (4, 'compression_enabled', '动态压缩', '缩小大声与小声的差距，让轻声更容易听清。'),
        ]:
            ttk.Checkbutton(frame, text=self.tr(label), variable=variables[key]).grid(row=row, column=0, columnspan=2, sticky='w', pady=3)
            ttk.Label(frame, text=self.tr(help_text), wraplength=650).grid(row=row, column=2, sticky='w', padx=8)
        advanced = ttk.Frame(frame)
        advanced_vars = {}
        advanced_inputs = []
        ttk.Label(advanced, text=self.tr('仅在“自定义”模式下可调整。没开启对应的声音处理时，修改参数不会改变音频。拿不准时保持默认值即可。'),
                  wraplength=780).grid(row=0, column=0, columnspan=3, sticky='w', pady=(0, 6))
        fields = [
            ('limiter_ceiling_dbfs', '峰值上限（-24 至 0 dBFS）', -24, 0,
             '防止突然很响的声音过大。数字越小，限制越强；如果听起来太闷，可以调大一点。只有开启“峰值限制”才生效。'),
            ('integrated_lufs', '目标响度（-30 至 -10 LUFS）', -30, -10,
             '设定节目整体听起来有多响。数字越接近 0，声音越响。只有开启“响度标准化”才生效；增益还会继续放大声音。'),
            ('threshold_db', '压缩阈值（-60 至 0 dBFS）', -60, 0,
             '决定从多大的声音开始压低音量。数字越小，越多声音会受到调整。只有开启“动态压缩”才生效。'),
            ('ratio', '压缩比例（1 至 20）', 1, 20,
             '决定大声的部分要压低多少。数字越大，大声和小声的差距越小；太高可能听起来不自然。只有开启“动态压缩”才生效。'),
        ]
        for row, (key, label, low, high, explanation) in enumerate(fields, start=1):
            advanced_vars[key] = tk.StringVar(value=str(values.get(key, AUDIO_PROCESSING[key])))
            ttk.Label(advanced, text=self.tr(label)).grid(row=row, column=0, sticky='w', padx=4, pady=4)
            spinner = ttk.Spinbox(advanced, textvariable=advanced_vars[key], from_=low, to=high, width=8)
            spinner.grid(row=row, column=1, padx=4, pady=4)
            advanced_inputs.append(spinner)
            ttk.Label(advanced, text=self.tr(explanation), wraplength=550).grid(row=row, column=2, sticky='w', padx=8, pady=4)
        def set_advanced_state():
            selected = preset.get()
            state = 'normal' if selected == self.tr('自定义') else 'disabled'
            for spinner in advanced_inputs:
                spinner.configure(state=state)
            preset_tip.set(self.tr('适合游泳时先试用的音量设置；效果因播放器、耳机和录音而异。')
                           if selected == self.tr('游泳增强') else
                           self.tr('不额外调整音量，只改变播放速度。') if selected == self.tr('仅倍速') else
                           self.tr('自行选择音量和声音处理；高级参数可在下方展开。'))
            if state == 'normal':
                advanced_button.grid()
            else:
                advanced.grid_remove()
                advanced_button.grid_remove()
        def reflect_edit(*_args):
            try:
                current = dict(AUDIO_PROCESSING, **values)
                current.update({key: variable.get() for key, variable in variables.items()})
                current['gain_db'] = float(current['gain_db'])
                current.update({key: float(variable.get()) for key, variable in advanced_vars.items()})
                preset.set(self.tr(preset_name(current)))
            except ValueError:
                preset.set(self.tr('自定义'))
            set_advanced_state()
        for variable in (*variables.values(), *advanced_vars.values()):
            variable.trace_add('write', reflect_edit)
        def toggle():
            if advanced.winfo_ismapped():
                advanced.grid_remove()
            else:
                advanced.grid(row=6, column=0, columnspan=3, sticky='w')
        advanced_button = ttk.Button(frame, text=self.tr('高级参数 ▾'), command=toggle)
        advanced_button.grid(row=5, column=0, sticky='w', pady=4)
        set_advanced_state()
        panel = (variables, advanced_vars, dict(values))
        if global_panel:
            self.global_audio = panel
        return panel

    def read_audio(self, panel):
        variables, advanced, base = panel
        result = dict(AUDIO_PROCESSING, **base)
        result.update({key: variable.get() for key, variable in variables.items()})
        result['gain_db'] = float(result['gain_db'])
        for key, variable in advanced.items():
            result[key] = float(variable.get())
        if result['gain_db'] not in (0, 3, 6, 9, 12) or not -24 <= result['limiter_ceiling_dbfs'] <= 0 or not -30 <= result['integrated_lufs'] <= -10 or not -60 <= result['threshold_db'] <= 0 or not 1 <= result['ratio'] <= 20:
            raise ValueError(self.tr('参数超出允许范围'))
        return result

    def save(self):
        self.settings.update(output_dir=self.output_var.get().strip(), player_dir=self.player_var.get().strip(),
                             transfer_mode=self.transfer_mode_var.get(), keep_originals=self.keep_var.get())
        engine.save_json(self.config_path, self.config)
        engine.save_json(self.settings_path, self.settings)

    def save_audio(self):
        try:
            self.settings['audio'] = self.read_audio(self.global_audio)
            self.save()
            self.refresh_programs()
            self.status_var.set(self.tr('设置已保存'))
        except (ValueError, OSError) as error:
            messagebox.showerror(self.tr('错误'), str(error), parent=self.root)

    def choose_output(self):
        chosen = filedialog.askdirectory(parent=self.root, initialdir=self.output_var.get())
        if chosen:
            self.output_var.set(chosen)
            self.save()

    def open_output(self):
        path = Path(self.output_var.get().strip())
        if not path.is_dir():
            messagebox.showerror(self.tr('错误'), self.tr('下载文件夹不存在'), parent=self.root)
            return
        os.startfile(str(path))

    def choose_player(self):
        chosen = filedialog.askdirectory(parent=self.root, initialdir=self.player_var.get() or ('E:/' if Path('E:/').exists() else None))
        if chosen:
            self.player_var.set(chosen)
            self.save()

    def refresh_programs(self):
        self.tree.delete(*self.tree.get_children())
        for index, podcast in enumerate(self.config.get('podcasts', [])):
            audio = engine.settings_for(podcast, self.settings.get('audio') or {})
            gain = audio['gain_db']
            source = self.tr('节目单独') if podcast.get('audio') else self.tr('全局默认')
            effects = ' · '.join('%s%s' % (self.tr(label), self.tr('开') if audio[key] else self.tr('关'))
                                 for key, label in [('limiter_enabled', '限幅'), ('normalization_enabled', '标准化'),
                                                    ('compression_enabled', '压缩')])
            self.tree.insert('', 'end', iid=str(index), values=(podcast['name'], '%gx' % podcast.get('speed', 1.5),
                              '%+g dB' % gain, effects, source, podcast.get('episodes', 1), podcast['rss']))

    def refresh_library(self):
        self.history = engine.load_json(self.history_path, {'episodes': {}})
        self.library_tree.delete(*self.library_tree.get_children())
        for key, record in sorted(self.history.get('episodes', {}).items(), key=lambda pair: pair[1].get('processed_at', ''), reverse=True):
            duration = record.get('output_seconds')
            duration = '%d:%02d' % (int(duration) // 60, int(duration) % 60) if duration else '—'
            verified = self.tr('已验证（含解码警告）') if record.get('verified') and record.get('decode_warnings') else (
                self.tr('已验证') if record.get('verified') else (
                self.tr('已有文件，仅验证可播放') if record.get('legacy_existing') and record.get('decode_checked') else self.tr('旧记录，待检查')))
            exists = self.tr('存在') if Path(record.get('file', '')).is_file() else self.tr('缺失')
            self.library_tree.insert('', 'end', iid=key, values=(record.get('podcast', ''), record.get('title', ''), duration, verified, exists))

    def dialog(self, initial=None):
        initial = initial or {}
        win = tk.Toplevel(self.root)
        win.title(self.tr('编辑节目'))
        win.geometry('970x620')
        win.transient(self.root)
        win.grab_set()
        frame = ttk.Frame(win, padding=12)
        frame.pack(fill='both', expand=True)
        variables = {}
        for key, label, default in [('name', '节目名称', ''), ('rss', 'RSS 地址', ''), ('speed', '倍速', 1.5), ('episodes', '检查最新集数', 2)]:
            row = ttk.Frame(frame)
            row.pack(fill='x', pady=4)
            ttk.Label(row, text=self.tr(label), width=20).pack(side='left')
            variable = variables[key] = tk.StringVar(value=str(initial.get(key, default)))
            if key == 'speed':
                ttk.Combobox(row, textvariable=variable, values=SPEEDS, state='readonly', width=10).pack(side='left')
            else:
                ttk.Entry(row, textvariable=variable).pack(side='left', fill='x', expand=True)
        inherit = tk.BooleanVar(value=not bool(initial.get('audio')))
        ttk.Checkbutton(frame, text=self.tr('使用全局音频设置（修改下方参数会自动改为本节目单独设置）'), variable=inherit).pack(anchor='w', pady=4)
        panel = self.audio_panel(frame, engine.settings_for(initial, self.settings.get('audio') or {}), False)
        for variable in (*panel[0].values(), *panel[1].values()):
            variable.trace_add('write', lambda *_args: inherit.set(False))
        result = {}
        def submit():
            try:
                name, rss = variables['name'].get().strip(), variables['rss'].get().strip()
                speed, count = float(variables['speed'].get()), int(variables['episodes'].get())
                if not name or not rss.startswith(('https://', 'http://')) or str(speed) not in SPEEDS or not 1 <= count <= 100:
                    raise ValueError(self.tr('请检查节目名称、RSS、倍速和集数（1–100）'))
                result.update(name=name, rss=rss, speed=speed, episodes=count)
                if not inherit.get():
                    result['audio'] = self.read_audio(panel)
                win.destroy()
            except ValueError as error:
                messagebox.showerror(self.tr('错误'), str(error), parent=win)
        row = ttk.Frame(frame)
        row.pack(pady=10)
        ttk.Button(row, text=self.tr('保存'), command=submit).pack(side='left', padx=6)
        ttk.Button(row, text=self.tr('取消'), command=win.destroy).pack(side='left')
        win.wait_window()
        return result or None

    def add(self):
        if self.running:
            return
        result = self.dialog()
        if result:
            if any(podcast['rss'].strip() == result['rss'] for podcast in self.config['podcasts']):
                messagebox.showerror(self.tr('错误'), self.tr('这个 RSS 地址已经存在'), parent=self.root)
                return
            self.config['podcasts'].append(result)
            self.save()
            self.refresh_programs()

    def edit(self):
        if self.running:
            return
        selected = self.tree.selection()
        if not selected:
            return
        index = int(selected[0])
        result = self.dialog(self.config['podcasts'][index])
        if result:
            self.config['podcasts'][index] = result
            self.save()
            self.refresh_programs()

    def delete(self):
        if self.running:
            return
        selected = self.tree.selection()
        if selected and messagebox.askyesno(self.tr('删除节目'), self.tr('删除所选节目配置？已下载文件保留。'), parent=self.root):
            for index in sorted(map(int, selected), reverse=True):
                del self.config['podcasts'][index]
            self.save()
            self.refresh_programs()

    def start_task(self, task):
        if self.running:
            return
        try:
            self.settings['audio'] = self.read_audio(self.global_audio)
            if not self.output_var.get().strip():
                raise ValueError(self.tr('请选择输出目录'))
            self.save()
        except (ValueError, OSError) as error:
            messagebox.showerror(self.tr('错误'), str(error), parent=self.root)
            return
        self.running = True
        self.control = engine.Control(self.status)
        for widget in self.task_buttons:
            widget.configure(state='disabled')
        self.language_widget.configure(state='disabled')
        self.pause_button.configure(state='normal', text=self.tr('暂停'))
        self.stop_button.configure(state='normal')
        self.status_var.set(self.render_log('running', ()))
        # Snapshot configuration before dispatch; workers never read Tk variables.
        self.task_settings = json.loads(json.dumps(self.settings))
        def worker():
            result = {'success': 0, 'skipped': 0, 'failed': 0}
            try:
                task(result)
            except engine.Stopped:
                result['stopped'] = True
            except Exception as error:
                result['failed'] += 1
                self.log('failed', str(error))
                engine.record_error(APP_DIR / 'error_log.txt', 'Task', error)
            finally:
                self.events.put(('done', result))
        threading.Thread(target=worker, daemon=True).start()

    def toggle_pause(self):
        if self.control.pause_event.is_set():
            self.control.resume()
            self.pause_button.configure(text=self.tr('暂停'))
        else:
            self.control.pause()
            self.pause_button.configure(text=self.tr('继续'))

    def stop(self):
        if self.control:
            self.control.stop()
            self.status_var.set(self.tr('正在停止，等待当前操作退出…'))
            self.pause_button.configure(state='disabled')
            self.stop_button.configure(state='disabled')

    def update_all(self):
        self.update_programs(self.config['podcasts'])

    def update_selected(self):
        self.update_programs([self.config['podcasts'][int(index)] for index in self.tree.selection()])

    def update_programs(self, podcasts):
        if not podcasts:
            messagebox.showinfo(self.tr('提示'), self.tr('请先添加或选择节目'), parent=self.root)
            return
        podcasts = json.loads(json.dumps(podcasts))
        def task(result):
            settings = self.task_settings
            result.update(engine.update_library(podcasts, settings['output_dir'], self.history_path,
                          settings['audio'], self.control, self.log, keep_originals=settings['keep_originals'],
                          error_log=APP_DIR / 'error_log.txt'))
        self.start_task(task)

    def selected_records(self):
        records = [(key, dict(self.history['episodes'][key])) for key in self.library_tree.selection()]
        if not records:
            messagebox.showinfo(self.tr('提示'), self.tr('请先选择单集'), parent=self.root)
        return records

    def redownload_selected(self):
        self.rebuild(False)

    def reprocess_selected(self):
        self.rebuild(True)

    def rebuild(self, reprocess):
        records = self.selected_records()
        if not records:
            return
        if not messagebox.askyesno(self.tr('提示'), self.tr('将使用当前设置重新生成所选节目，成功后替换同名文件。是否继续？'), parent=self.root):
            return
        podcasts = json.loads(json.dumps(self.config['podcasts']))
        def task(result):
            settings = self.task_settings
            output = Path(settings['output_dir'])
            output.mkdir(parents=True, exist_ok=True)
            cache = output / '.swimcast_originals'
            cache.mkdir(exist_ok=True)
            history = engine.load_json(self.history_path, {'episodes': {}})
            for key, record in records:
                self.control.checkpoint()
                url = record.get('audio_url')
                if not url:
                    result['failed'] += 1
                    self.log('failed', self.tr('旧记录没有音频地址，请更新节目 RSS'))
                    continue
                podcast = next((p for p in podcasts if p['name'] == record['podcast']),
                               {'name': record['podcast'], 'rss': record.get('rss', ''), 'speed': record.get('speed', 1.5)})
                item = {'title': record['title'], 'itunes_duration': record.get('rss_seconds')}
                # Refresh feed metadata/URL when still available (expiring URLs and source revisions).
                if podcast.get('rss'):
                    try:
                        entries = engine.fetch_feed(podcast['rss'], self.control, self.log)
                        for candidate in entries:
                            candidate_url = engine.find_audio_url(candidate)
                            if candidate_url and (engine.episode_key(candidate, candidate_url) == key or candidate.get('title') == record['title']):
                                item, url = candidate, candidate_url
                                break
                    except engine.Stopped:
                        raise
                    except Exception as error:
                        self.log('feed_fallback', str(error))
                self.log('episode', record['title'])
                engine.process_episode(item, podcast, key, url, record, output, cache, history,
                                       self.history_path, settings['audio'], self.control, self.log,
                                       result, True, reprocess, settings['keep_originals'], APP_DIR / 'error_log.txt')
        self.start_task(task)

    def check_selected(self):
        records = self.selected_records()
        if not records:
            return
        def task(result):
            history = engine.load_json(self.history_path, {'episodes': {}})
            for key, record in records:
                self.control.checkpoint()
                self.log('episode', record['title'])
                try:
                    duration, warnings = engine.inspect_audio_details(record['file'], self.control)
                    if warnings:
                        self.log('decode_warning')
                    source_duration = record.get('source_seconds')
                    if source_duration:
                        engine.verify_processed(source_duration, duration, record.get('speed', 1))
                        history['episodes'][key]['verified'] = True
                    else:
                        self.log('legacy_check')
                    history['episodes'][key]['output_seconds'] = duration
                    history['episodes'][key]['decode_checked'] = True
                    history['episodes'][key]['decode_warnings'] = warnings
                    engine.save_json(self.history_path, history)
                    result['success'] += 1
                    self.log('file_checked', duration)
                except engine.Stopped:
                    raise
                except Exception as error:
                    history['episodes'][key]['verified'] = False
                    engine.save_json(self.history_path, history)
                    result['failed'] += 1
                    self.log('failed', str(error))
        self.start_task(task)

    def ask_replace(self, filename):
        ready, answer = threading.Event(), []
        text = self.tr('播放器已有同名但内容不同的文件。替换？') + '\n' + filename
        self.events.put(('ask', text, answer, ready))
        while not ready.wait(.1):
            self.control.check_stop()
        self.control.check_stop()
        return answer[0]

    def transfer_selected(self):
        records = self.selected_records()
        if not records:
            return
        if not self.player_var.get().strip():
            self.choose_player()
        player = Path(self.player_var.get().strip())
        if not self.player_var.get().strip() or not player.is_dir():
            messagebox.showerror(self.tr('错误'), self.tr('播放器未连接或目标文件夹不存在'), parent=self.root)
            return
        available = []
        missing = []
        for key, record in records:
            source = engine.locate_audio_file(record, self.output_var.get().strip())
            if source is None:
                missing.append(record.get('title', ''))
            else:
                available.append((key, record, source))
        if missing:
            messagebox.showerror(self.tr('错误'),
                                 self.tr('找不到音频文件，请重新下载后再传输：{}').format('\n'.join(missing)),
                                 parent=self.root)
        if not available:
            return
        def task(result):
            mode = self.task_settings.get('transfer_mode', 'copy')
            history = engine.load_json(self.history_path, {'episodes': {}})
            for key, record, source in available:
                self.control.checkpoint()
                self.log('episode', record['title'])
                target = player / source.name
                try:
                    if not player.is_dir():
                        raise RuntimeError(self.tr('播放器未连接或目标文件夹不存在'))
                    if not source.is_file():
                        result['failed'] += 1
                        self.log('missing_source', record['title'])
                        continue
                    saved_record = history.get('episodes', {}).get(key)
                    if saved_record is not None and saved_record.get('file') != str(source):
                        saved_record['file'] = str(source)
                        engine.save_json(self.history_path, history)
                    if os.path.normcase(os.path.abspath(source)) == os.path.normcase(os.path.abspath(target)):
                        result['skipped'] += 1
                        self.log('already_in_player')
                        continue
                    outcome = None
                    for attempt in range(3):
                        try:
                            outcome = engine.transfer_audio(source, target, mode, self.control)
                            break
                        except FileNotFoundError:
                            raise
                        except (OSError, RuntimeError):
                            if attempt == 2 or not player.is_dir():
                                raise
                            self.log('retry', attempt + 2, 3)
                            self.control.delay(2)
                    if outcome == 'conflict':
                        if self.ask_replace(target.name):
                            outcome = engine.transfer_audio(source, target, mode, self.control, replace=True)
                        else:
                            outcome = 'skipped'
                    if outcome in ('copied', 'moved'):
                        saved_record = history.get('episodes', {}).get(key)
                        if saved_record is not None:
                            saved_record['transferred_to'] = str(target)
                            saved_record['transfer_mode'] = mode
                            if outcome == 'moved':
                                saved_record['file'] = str(target)
                            engine.save_json(self.history_path, history)
                        result['success'] += 1
                        self.log('transfer_moved' if outcome == 'moved' else 'transfer_ok')
                    else:
                        result['skipped'] += 1
                        self.log('transfer_identical' if outcome == 'identical' else 'skipped')
                except engine.Stopped:
                    raise
                except FileNotFoundError:
                    result['failed'] += 1
                    self.log('missing_source', record['title'])
                except Exception as error:
                    result['failed'] += 1
                    self.log('failed', str(error))
        self.start_task(task)

    def audition(self):
        records = self.selected_records()
        if len(records) != 1:
            if records:
                messagebox.showinfo(self.tr('提示'), self.tr('试听请选择一集'), parent=self.root)
            return
        key, record = records[0]
        source = Path(record.get('original_file') or '')
        if not source.is_file():
            messagebox.showinfo(self.tr('提示'), self.tr('此集没有保留原音，请选择未经处理的原音文件'), parent=self.root)
            chosen = filedialog.askopenfilename(parent=self.root, filetypes=[(self.tr('音频文件'), '*.mp3 *.m4a *.wav *.audio'), (self.tr('所有文件'), '*.*')])
            if not chosen:
                return
            source = Path(chosen)
        destination = filedialog.askdirectory(parent=self.root, title=self.tr('选择试听输出目录'))
        if not destination:
            return
        podcast = next((dict(p) for p in self.config['podcasts'] if p['name'] == record['podcast']), dict(record))
        def task(result):
            import tempfile
            folder = Path(tempfile.mkdtemp(prefix='SwimCast_AB_', dir=destination))
            settings = engine.settings_for(podcast, self.task_settings['audio'])
            baseline = dict(settings, gain_db=0, limiter_enabled=False, compression_enabled=False, normalization_enabled=False)
            speed = podcast.get('speed', 1.5)
            for name, audio in [('A_speed_only.mp3', baseline), ('B_selected_settings.mp3', settings)]:
                self.control.checkpoint()
                target = folder / name
                try:
                    engine.run_process([engine.ffmpeg_path(), '-y', '-nostdin', '-v', 'error', '-xerror',
                        '-t', '60', '-i', str(source), '-vn', '-filter:a', engine.audio_filter(speed, audio),
                        '-ar', '44100', '-codec:a', 'libmp3lame', '-b:a', '128k', str(target)], self.control)
                except BaseException:
                    target.unlink(missing_ok=True)
                    raise
                result['success'] += 1
            self.log('audition_ok', str(folder))
        self.start_task(task)

    def close(self):
        if self.running:
            if messagebox.askyesno(self.tr('退出'), self.tr('停止当前任务并退出？已完成结果会保留。'), parent=self.root):
                self.closing = True
                self.stop()
        else:
            self.save()
            self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    try:
        App(root)
        root.mainloop()
    except Exception as error:
        messagebox.showerror('SwimCast', str(error), parent=root)
        root.destroy()
