# Atmospheric Document & Web Reader

Read live web pages, PDFs, `.txt` and `.md` files over a custom wallpaper (image or video) with looping background music.
Presets, called **atmospheres**, bundle **content + background + music** under one name.

## Quick start

You need [Python](https://www.python.org/downloads/) 3.9–3.13 (PySide6 6.9 is the tested version).

```bash
git clone https://github.com/YOUR-USERNAME/atmospheric-reader.git
cd atmospheric-reader
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

If `python` on your PATH is 3.14, run with an older version: `py -3.11 main.py` (or the full path to its `python.exe`).

## Features

- **Reads anything:** live web pages, PDFs, text and Markdown files, and local videos or direct video links.
- **Atmospheres:** content, wallpaper and music saved together under one name. The content field is optional: an atmosphere with only a wallpaper and music applies them instantly to whatever is already open.
- **Video wallpapers:** `.mp4 .webm .mkv .mov .avi .m4v .wmv`, looping silently behind the app. Web pages get them too.
- **Frosted-glass UI:** blurred-wallpaper panels, a glass bezel around the content, and a right-hand **scroll rail** (drag, page up/down, top/bottom, auto-scroll with a speed slider) that works for web pages, PDFs and text.
- **Resume reading:** the scroll position of every PDF, text file and web page is remembered.
- **Sidebar organization:** folders, drag-to-reorder, search, and a pinned **Startup** slot.
- **Zen mode:** hides the panels and leaves only wallpaper and content.
- **Low CPU:** the window's own video copy pauses when it can't be seen (minimized, covered by the browser, or optionally when the app is unfocused).

## Shortcuts

| Key | Action |
| --- | --- |
| **F11** | Fullscreen (**Esc** leaves it) |
| **F10** | Zen mode (**Esc** leaves it) |
| **Ctrl+B** | Show / hide the sidebar |
| **Ctrl +** / **Ctrl −** | Larger / smaller text |

## Using it

### Atmospheres, folders and the Startup slot

The sidebar groups atmospheres into folders. This is UI only: nothing is created on your PC, and it is saved in `presets.json`.

- **New folder** button, or right-click empty space. Click a folder to show or hide its atmospheres; it remembers open/closed.
- Drag an atmosphere onto a folder (or between its rows) to file it. Right-click → *Move to folder* does the same.
- Right-click a folder to rename it, move it up/down or delete it (its atmospheres are kept).
- **Startup** is the pinned slot at the very top. The atmosphere in it opens first every time the app starts. Right-click an atmosphere → *Set as startup atmosphere*, or drag it onto the slot. Drag it out, or use *Remove from Startup*, to clear it.

### Video wallpapers

A preset's background can be a video. It loops silently behind the app, and the preset's music is separate. Videos over 200 MB are referenced in place instead of being copied into the assets folder.

**Lowest-CPU playback in web pages.** The app first lets the browser engine play the wallpaper itself (hardware decoding, almost no CPU). This works for formats Chromium can play, mainly **WebM (VP9/AV1)**. If it can't, the app streams decoded frames into the page at about 25 fps instead, which is heavier on the CPU. The sidebar shows which mode is active.

**Automatic WebM conversion.** Choosing a non-WebM video as a background asks for a destination folder (the last one is remembered), then converts it to VP9 WebM with a cancellable progress dialog. The resolution and frame rate stay the same, and audio is dropped since wallpapers are silent. The converted file stays in the folder you chose, so don't move it. The original is untouched.

This needs **ffmpeg**: download `ffmpeg-release-essentials.zip` from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/), then either put `ffmpeg.exe` next to `main.py` or add it to your PATH. Without ffmpeg the original video is used and frames are streamed.

To convert by hand:

```
ffmpeg -i input.mp4 -c:v libvpx-vp9 -b:v 0 -crf 30 -an output.webm
```

### Videos as content

Content can be a local video or a direct link to one. Playback uses the OS codecs (Windows Media Foundation), and the background music ducks while a video plays.

### PDF bookmarks

PDF atmospheres have a one-page bookmark, saved with the atmosphere.

- Closing the app while reading its PDF on a page other than the saved one asks **"Save your page before leaving?"**
- Right-click the open PDF atmosphere → **Save bookmark here (page N)**, or **Remove bookmark**.
- An atmosphere with a bookmark always reopens at that page, replacing the automatic reading position. Hover it in the sidebar to see the page.
- Changing the atmosphere's PDF in *Edit* clears the bookmark. A PDF opened another way (address bar, drag and drop) is never bookmarked into the atmosphere.

### Update the chapter on exit

When you close the app while reading a web page that differs from the active atmosphere's saved address, it asks **"Update the chapter before leaving?"** Yes saves the current page as that atmosphere's URL (only the URL changes: name, wallpaper, music and folder stay), so it reopens at your chapter. It doesn't ask when the atmosphere has no web address, when something other than a web page is open, or when the address is already the same.

Right-click an atmosphere with a web address → **Update chapter to the current page** does the same at any time. It is enabled for the atmosphere you are reading when the page differs from its saved address.

### Update the Startup atmosphere on exit

If you close the app inside an atmosphere that has no web address (wallpaper and music only) while reading a web page, it asks **"Update the Startup atmosphere “name” before leaving?"** Yes saves the page as the web address of the atmosphere in the Startup slot (only that URL changes). It only asks when the Startup atmosphere has a web address that differs from the page.

## Where your data lives

Everything is stored under `QStandardPaths.AppDataLocation/AtmosphericReader/`:

| OS | Location |
| --- | --- |
| Windows | `%APPDATA%\AtmosphericReader` |
| Linux | `~/.local/share/AtmosphericReader` |
| macOS | `~/Library/Application Support/AtmosphericReader` |

- `presets.json` holds the atmospheres and settings (volume, panel opacity, last preset).
- `assets/` holds background images and audio, copied there when a preset is saved.
- URLs are stored as-is. PDF and text documents are referenced in place, so edits show up live.

## Project layout

```
main.py                 entry point
requirements.txt        dependencies
reader/presets.py       Preset dataclass, JSON store, asset import
reader/audio.py         QMediaPlayer wrapper (loop, volume, cross-fade)
reader/viewers.py       WebViewer (WebEngine), TextViewer (txt/md)
reader/pdfview.py       PdfViewer (QtPdf), loaded when the first PDF is opened
reader/videoview.py     VideoViewer, loaded when the first video is opened
reader/transcode.py     WebM conversion through ffmpeg
reader/dialogs.py       create/edit preset dialog
reader/window.py        background canvas, sidebar, wiring
reader/glass.py         wallpaper canvas, glass panels, scroll rail
reader/icons.py         in-app SVG icons (rendered at the exact pixel size)
icon.svg / icon.ico     app icon
```
