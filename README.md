# Lingo

适用于 GNOME / Wayland 的壁纸管理应用，使用 GTK 4 和 libadwaita。

## 启动

需要 Python 3.11+、GTK 4.10+、libadwaita 1.4+，以及系统提供的 PyGObject 和 Pillow。推荐安装 `curl`，用于为搜索、缩略图和图片下载提供涵盖连接与传输的总超时。

```bash
python main.py gui
```

安装命令行入口和用户级定时任务：

```bash
python main.py install
# 仅安装文件，不启动或启用定时任务
python main.py install --no-enable
```

## 使用

- **Browse**：添加图片、导入文件夹、点击图片设为壁纸、切换上一张或下一张、打开收藏夹文件夹。
- **Collections**：右键重命名或删除；删除收藏夹会保留磁盘上的图片，至少保留一个收藏夹。重命名保留原有文件夹路径和图片历史。
- 图片左上角的复制按钮可以将图片加入另一个收藏夹；遇到同名文件会自动编号。
- 图片删除按钮将文件移入系统回收站。
- **Search**：选择 DDG、Bing、Wallhaven 或 Wikimedia Commons，按尺寸搜索、全选或清空、加载更多、打开图片来源。下载按钮右侧选择保存到哪个收藏夹。
- Bing 默认使用 Any 尺寸；选择其他尺寸时在本地筛选，Wallpaper 指至少 1920×1080。某页没有符合尺寸的图片时，仍可点击 Load more。
- 下载前会检查图片内容，显示新增、已存在和失败数量；错误详情可以通过状态文字的悬浮提示查看。
- **Settings**：调整模糊背景、适应、裁剪填充、拉伸或居中，以及时钟位置、字体大小、12/24 小时制或自定义 `strftime` 格式。
- 支持按分钟间隔更新、每天当地时间指定时刻更新或仅手动更新。时钟每分钟刷新；“开机启动”指登录图形桌面后启动壁纸任务，不会自动打开设置窗口。
- 每天指定时间更新会在该时间之后的首次定时检查补上当天更新。“登录时更换壁纸”可以单独控制。

快捷键：`Ctrl+F` 打开搜索、`Ctrl+R` 刷新收藏夹、`Alt+Left` / `Alt+Right` 切换壁纸。

配置保存在 `~/.config/lingo/config.toml`，缓存和历史保存在 `~/.cache/lingo/`，支持 `XDG_CONFIG_HOME` 和 `XDG_CACHE_HOME`。

## 搜索来源

Bing 和 DDG 依赖网页接口，可能出现验证页、限流或页面结构变化；遇到错误可以重试或切换来源。Wallhaven 和 Wikimedia Commons 使用 JSON API。Commons 的来源页面提供作者和许可信息。

接口参考：[Wallhaven](https://wallhaven.cc/help/api)、[MediaWiki Search](https://www.mediawiki.org/wiki/API:Search)、[MediaWiki Imageinfo](https://www.mediawiki.org/wiki/API:Imageinfo)。

## 检查

```bash
python -m unittest discover -s tests -v
python -m compileall -q .
# 有图形会话时，包含 GTK 控件回归检查
GSETTINGS_BACKEND=memory LINGO_GUI_TEST=1 python -m unittest discover -s tests -v
```
