# SwimCast Manager

[English](#english) | [简体中文](#简体中文)

## 简体中文

SwimCast 是 Windows 上的播客 RSS 下载、倍速处理和 MP3 播放器传输工具。本版增加完整性检查、任务暂停与停止、中英文界面、音频设置和传输校验。

### 安装与启动

1. 下载本仓库的 ZIP 并解压到你选择的文件夹。先安装 Python 3.9 或更新版本；安装 Python 时勾选 **Add Python to PATH**。如果电脑已有 Anaconda，也可以使用它自带的 Python。
2. 在解压后的文件夹里双击 `install_swimcast.bat`。它会在程序文件夹内创建独立的 `.venv` 环境，并把 SwimCast 所需的 Python 依赖安装到这里，不会改动现有 Python 环境中的依赖；它不会安装 Python 或 FFmpeg。
3. **FFmpeg 不包含在本仓库中，需要单独下载。**请从 [FFmpeg 下载页](https://ffmpeg.org/download.html) 进入 Windows 构建版本下载链接，解压后在 `bin` 文件夹找到 `ffmpeg.exe`。把该文件复制到与 `swimcast_manager.py` 同一文件夹；如果已经把 FFmpeg 加入系统 PATH，则无需复制。
4. 双击 `start_swimcast.bat` 启动程序。

熟悉命令行的用户也可以跳过第 2 步：在文件资源管理器打开解压后的文件夹，点击顶部地址栏，输入 `cmd` 并按回车；在弹出的命令窗口中依次输入 `python -m venv .venv`、`.venv\Scripts\python.exe -m pip install -r requirements.txt`。之后双击 `start_swimcast.bat` 启动。如果使用 Anaconda，请先激活正确的 Python 环境。

从旧版升级时，先退出旧程序，备份并复制 `podcast_config.json`、`settings.json`、`download_history.json` 到新版文件夹；如需保留已有下载和原音，也请自行复制对应文件夹。旧记录没有原音时长，因此不能追溯证明它们的内容完整。首次更新不会重复下载已有历史的节目。

### 卸载

SwimCast 目前是解压后运行的程序，不会注册到 Windows 的“已安装的应用”。退出程序后，先备份想保留的订阅配置、设置、下载历史和音频，再删除解压出的程序文件夹即可。默认下载文件夹和 SwimCast 专用的 `.venv` 环境都位于程序文件夹内，会随之一起删除；如果曾改用外部下载文件夹，请自行检查并决定是否保留那里的音频。删除程序文件夹不会卸载电脑上原有的 Python 或 FFmpeg。

### 主要功能

- “更新全部节目”或“更新所选节目”检查 RSS。程序重试临时下载故障，核对服务器提供的长度，解码原音和输出，比较实际时长与倍速预期，再记录成功。少量可恢复的 MP3 坏帧会作为警告显示，不会让整集失败；建议试听有警告的节目。
- 如果共享输出目录里已有旧版生成的同名 MP3，新版先检查其可解码性和 RSS 时长，再将其记为已有文件并跳过重复下载。此类旧文件没有原音可供追溯，状态会显示“已有文件，仅验证可播放”；若要按新设置生成，请使用“重新下载”。
- RSS 标注时长若比下载原音长超过 20% 且相差超过 30 秒，程序拒收并记录错误。这只能提示疑似截断；播客提供方更换广告、修订音源或 RSS 时长不准也可能触发。
- 下载和传输时会自动检查音频；无需手动运行检查。旧记录缺少原音时长，不能追溯确认内容完整；如有疑虑，请选“重新下载”。
- “重新处理”优先使用保留的原音；没有保留原音则重新下载。默认保留原音以便修改设置后重新处理，会增加磁盘使用量。
- 设置页提供“仅倍速”“游泳增强”和“自定义”。游泳增强适合游泳时先试用，效果因播放器、耳机和录音而异。增益可选 0、+3、+6、+9、+12 dB；默认游泳增强为 +9 dB、峰值限制开启，响度标准化和动态压缩关闭。高级参数仅在自定义模式下显示并可修改；只有开启相应的音频处理后参数才生效。设置页可独立滚动，保存按钮固定在底部。可对单个节目覆盖全局设置。
- “短片段 A/B 试听”从原音生成开头约 60 秒的两份文件，A 仅倍速，B 使用当前节目设置。原音未保留时需手动选取未经处理的文件。
- “传输到播放器”会将所选音频直接放入指定文件夹。设置页可选择复制（默认保留下载文件）或移动（校验后删除下载文件）。复制后重新读取目标文件并比较大小及 SHA-256；同名但内容不同的文件会询问是否替换。移动成功后历史记录指向播放器中的文件。连接播放器后，请在设置页选择它当前显示的文件夹；设备路径变化时重新选择。
- “音频库与传输”页可直接打开下载文件夹；节目区与运行日志区之间的分隔线可拖动调整高度。
- 暂停下载会关闭当前连接，继续后重新下载当前集。暂停转换将在当前集完成验证后生效；停止会中断当前任务并清理临时文件。已完成的结果保留。

### 限制与隐私

传输校验只能证明播放器里的文件与电脑上的一致，不能证明播放器一定能正常播放。RSS 时长也不是可靠的绝对真值。程序不会识别“已听完”，也不会自动删除音频。

个人订阅源、历史、日志、原音、输出音频和 FFmpeg 可执行文件均不应提交到公开仓库；`.gitignore` 已排除这些文件。`podcast_config.example.json` 只是无个人数据的示例。`error_log.txt` 可能包含带令牌的订阅地址，应保留在本机。

## English

SwimCast is a Windows RSS podcast downloader, audio processor, and MP3-player transfer tool. Version 3 adds integrity checks, pause/stop controls, Chinese/English UI, audio settings, and verified copying.

### Install and run

1. Download this repository as a ZIP and extract it to a folder of your choice. Install Python 3.9+ and select **Add Python to PATH** during setup. An existing Anaconda Python installation can also be used.
2. Double-click `install_swimcast.bat` in the extracted folder. It creates a private `.venv` environment inside the program folder and installs SwimCast's Python dependencies there, without changing packages in an existing Python environment. It does not install Python or FFmpeg.
3. **FFmpeg is not included in this repository and must be downloaded separately.** Visit the [FFmpeg download page](https://ffmpeg.org/download.html), follow a Windows build link, and find `ffmpeg.exe` in the extracted `bin` folder. Copy it beside `swimcast_manager.py`, or add FFmpeg to your system PATH.
4. Double-click `start_swimcast.bat` to launch the app.

If you prefer the command line, skip step 2: open the extracted folder in File Explorer, click its address bar, type `cmd`, and press Enter. In the command window, run `python -m venv .venv`, then `.venv\Scripts\python.exe -m pip install -r requirements.txt`. Double-click `start_swimcast.bat` to launch. Activate the intended Python environment first if you use Anaconda.

To upgrade, exit the old app and back up/copy `podcast_config.json`, `settings.json`, and `download_history.json` into this folder. Copy your downloads and retained originals as well if you want to keep them. Legacy records lack original-audio duration and cannot be retrospectively certified as complete. Existing history is skipped on ordinary updates.

### Uninstall

SwimCast currently runs from an extracted folder and is not registered under Windows Installed apps. Exit the app and back up any podcast configuration, settings, download history, or audio you want to keep before deleting the extracted program folder. The default download folder and SwimCast's private `.venv` environment are inside the program folder and will be deleted with it. If you chose an external download folder, review those audio files separately. Deleting the program folder does not remove Python or FFmpeg installed elsewhere on your computer.

### Features

- Update all or selected podcasts. Temporary download failures are retried. When provided, HTTP content length is checked. The original and output audio are decoded, and actual durations are compared with the chosen playback speed before a success record is written. Recoverable MP3 frame errors appear as warnings instead of failing the whole episode; audition episodes with warnings.
- If an older version already created a matching MP3 in the shared output directory, the app checks decodability and advertised duration, records it as an existing file, and skips the duplicate download. Its original audio cannot be retrospectively verified. Use Download again to apply new processing settings.
- An original shorter than 80% of the RSS duration by at least 30 seconds is rejected. RSS durations can be inaccurate or differ after ad insertion, so this is a warning threshold rather than proof of corruption.
- Downloads and transfers are checked automatically; there is no manual check step. Without the original duration, legacy files cannot be retrospectively certified as complete. Use Download again if in doubt.
- Reprocess retained originals with changed settings; download again when originals are unavailable. Originals are kept by default and use extra disk space.
- Choose speed only, swimming boost, or custom processing. Swimming boost is a starting point for swimming; results vary by player, headphones, and recording. Gain options are 0, +3, +6, +9, and +12 dB. The swimming default uses +9 dB and peak limiting; normalization and compression are off. Advanced parameters appear in Custom mode and matter only while their processing option is enabled. The Settings page scrolls independently and keeps Save settings at the bottom. Override global settings for individual podcasts.
- Create roughly 60-second A/B samples: A uses speed only; B uses selected processing.
- Transfer selected episodes directly into a mounted player folder. Choose Copy (default, keeps the download) or Move (deletes the download only after the destination passes size and SHA-256 verification). Existing different files require confirmation before replacement. A moved episode's history points to its file on the player.
- Open the download folder from Library & transfer. Drag the divider between the podcast area and activity log to resize them.
- Pause a download by closing its connection and restarting that episode on resume. Conversion reaches its next episode boundary before pausing. Stop aborts the current operation and removes partial files while keeping completed results.

### Limits and privacy

Transfer verification proves file identity, not device playback. RSS duration is advisory. The app does not detect listened episodes or delete them automatically.

Do not publish personal RSS URLs, history, logs, original or processed audio, or FFmpeg binaries. `.gitignore` excludes these. The sample configuration contains no personal data. Error logs may contain subscription tokens and should stay local.
