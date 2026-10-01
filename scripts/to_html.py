#!/usr/bin/env python3
'''
    Renders mattermost-dl archive into static offline HTML: index page plus one page per channel.
    Attachments are referenced by relative links into the archive, nothing is copied.

    Usage: to_html.py <archive-dir> [<html-dir>]
'''

import html
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

EMOJI = {
    '+1': '👍', 'thumbsup': '👍', '-1': '👎', 'thumbsdown': '👎', 'smile': '😄', 'smiley': '😃',
    'slightly_smiling_face': '🙂', 'grinning': '😀', 'joy': '😂', 'laughing': '😆', 'rofl': '🤣',
    'wink': '😉', 'heart': '❤️', 'heart_eyes': '😍', 'ok_hand': '👌', 'pray': '🙏', 'clap': '👏',
    'fire': '🔥', 'tada': '🎉', 'thinking': '🤔', 'thinking_face': '🤔', 'eyes': '👀', 'white_check_mark': '✅',
    'heavy_check_mark': '✔️', 'x': '❌', 'cry': '😢', 'sob': '😭', 'sweat_smile': '😅', 'disappointed': '😞',
    'rage': '😡', 'muscle': '💪', 'rocket': '🚀', 'handshake': '🤝', 'facepalm': '🤦', 'man_facepalming': '🤦‍♂️',
    'upside_down_face': '🙃', 'neutral_face': '😐', 'confused': '😕', 'scream': '😱', 'beer': '🍺', 'coffee': '☕',
    'point_up': '☝️', 'v': '✌️', 'wave': '👋', 'sunglasses': '😎', 'blush': '😊', 'stuck_out_tongue': '😛',
    'relieved': '😌', 'hugs': '🤗', 'hugging_face': '🤗', 'star': '⭐', 'warning': '⚠️', '100': '💯',
}

CSS = '''
body{font:15px/1.45 system-ui,sans-serif;margin:0;background:#f5f6f8;color:#1f2329}
header{position:sticky;top:0;background:#1e325c;color:#fff;padding:10px 20px;z-index:1}
header a{color:#cfe0ff} header h1{font-size:18px;margin:0} header .sub{font-size:13px;opacity:.8}
main{max-width:1000px;margin:0 auto;padding:10px 20px 60px}
.day{text-align:center;margin:22px 0 8px;color:#6b7280;font-size:13px;font-weight:600}
.post{display:flex;gap:10px;padding:6px 8px;border-radius:6px} .post:hover{background:#fff}
.post:target{background:#fff6d6}
.ava{width:36px;height:36px;border-radius:50%;flex:none;background:#d6dbe3;object-fit:cover}
.body{min-width:0;flex:1} .who{font-weight:600} .time{color:#8a9099;font-size:12px;margin-left:6px}
.time a{color:inherit;text-decoration:none}
.msg{white-space:normal;overflow-wrap:anywhere} .sys .msg{color:#6b7280;font-style:italic}
.reply{font-size:12px;color:#6b7280;border-left:3px solid #c8d1e0;padding-left:6px;margin:2px 0}
.reply a{color:#4a5a78}
pre{background:#272b33;color:#e6e6e6;padding:8px 10px;border-radius:6px;overflow-x:auto;font-size:13px}
code{background:#e8eaee;padding:0 3px;border-radius:3px;font-size:13px} pre code{background:none;padding:0}
.files{display:flex;flex-wrap:wrap;gap:8px;margin-top:4px}
.files img{max-width:420px;max-height:320px;border-radius:6px;border:1px solid #d6dbe3;display:block}
.file{font-size:13px;background:#fff;border:1px solid #d6dbe3;border-radius:6px;padding:4px 8px}
.file.missing{color:#8a9099;border-style:dashed}
.react{display:inline-block;font-size:12px;background:#eef1f6;border-radius:10px;padding:0 7px;margin:3px 4px 0 0}
table{border-collapse:collapse;width:100%;background:#fff} td,th{padding:6px 10px;border-bottom:1px solid #e5e7eb;text-align:left}
th{background:#eef1f6;font-size:13px} td.n{text-align:right;font-variant-numeric:tabular-nums}
input#q{width:100%;padding:8px;font-size:15px;margin:10px 0;box-sizing:border-box}
.mention{color:#2457c5;font-weight:600}
'''

TYPE_LABEL = {'Direct': 'личка', 'Group': 'группа', 'Private': 'приватный', 'Open': 'публичный'}


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def fmtSize(n: int) -> str:
    for unit in ('Б', 'КБ', 'МБ', 'ГБ'):
        if n < 1024 or unit == 'ГБ':
            return f'{n:.0f} {unit}' if unit == 'Б' else f'{n:.1f} {unit}'
        n /= 1024
    return str(n)


def ts(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000)


def displayName(user: dict) -> str:
    full = ' '.join(x for x in (user.get('firstName'), user.get('lastName')) if x)
    return full or user.get('nickname') or user.get('name') or user.get('id', '?')


INLINE_RE = re.compile(
    r'(?P<code>`[^`\n]+`)'
    r'|(?P<link>\[(?P<ltext>[^\]\n]+)\]\((?P<lurl>https?://[^)\s]+)\))'
    r'|(?P<url>https?://[^\s<>()]+[^\s<>().,;:!?"\'])'
    r'|(?P<bold>\*\*(?P<btext>[^*\n]+)\*\*)'
    r'|(?P<strike>~~(?P<stext>[^~]+)~~)'
    r'|(?P<mention>@[\w.\-]+)'
    r'|(?P<emoji>:(?P<ename>[\w+\-]+):)'
)


def renderInline(text: str) -> str:
    out = []
    pos = 0
    for m in INLINE_RE.finditer(text):
        out.append(esc(text[pos:m.start()]))
        pos = m.end()
        if m['code']:
            out.append(f'<code>{esc(m["code"][1:-1])}</code>')
        elif m['link']:
            out.append(f'<a href="{esc(m["lurl"])}">{esc(m["ltext"])}</a>')
        elif m['url']:
            out.append(f'<a href="{esc(m["url"])}">{esc(m["url"])}</a>')
        elif m['bold']:
            out.append(f'<b>{esc(m["btext"])}</b>')
        elif m['strike']:
            out.append(f'<s>{esc(m["stext"])}</s>')
        elif m['mention']:
            out.append(f'<span class="mention">{esc(m["mention"])}</span>')
        elif m['emoji']:
            out.append(EMOJI.get(m['ename'], esc(m['emoji'])))
    out.append(esc(text[pos:]))
    return ''.join(out).replace('\n', '<br>')


def renderMessage(text: str) -> str:
    parts = re.split(r'```[^\n]*\n?(.*?)```', text, flags=re.S)
    out = []
    for i, part in enumerate(parts):
        if i % 2:
            out.append(f'<pre><code>{esc(part.rstrip())}</code></pre>')
        elif part.strip():
            out.append(renderInline(part.strip('\n')))
    return ''.join(out)


def snippet(text: str, limit: int = 90) -> str:
    text = ' '.join((text or '').split())
    return text if len(text) <= limit else text[:limit] + '…'


class Channel:
    def __init__(self, archive: Path, metaFile: Path):
        self.base = metaFile.name[:-len('.meta.json')]
        self.meta = json.loads(metaFile.read_text(encoding='utf-8'))
        self.info = self.meta['channel']
        self.users = {u['id']: u for u in self.meta.get('users', [])}
        dataFile = archive / (self.base + '.data.json')
        self.posts = []
        if dataFile.exists():
            with open(dataFile, encoding='utf-8') as fp:
                self.posts = [json.loads(line) for line in fp if line.strip()]
        self.posts.sort(key=lambda p: p['createTime'])
        filesDir = archive / (self.base + '--files')
        self.files = {Path(n).stem: n for n in os.listdir(filesDir)} if filesDir.is_dir() else {}

    def title(self, me: str) -> str:
        kind = self.info.get('type')
        if kind in ('Direct', 'Group'):
            others = [displayName(u) for u in self.users.values() if u['name'] != me]
            if others:
                return ', '.join(sorted(others))
            if kind == 'Direct' and self.users:
                return displayName(next(iter(self.users.values()))) + ' (заметки себе)'
        return self.info.get('name') or self.info.get('internalName') or self.base


def renderChannel(ch: Channel, me: str, archiveRel: str, allUsers: dict) -> str:
    users = {**allUsers, **ch.users}
    byId = {p['id']: p for p in ch.posts}
    title = ch.title(me)
    kind = TYPE_LABEL.get(ch.info.get('type'), ch.info.get('type', ''))
    archived = ' · архивный' if ch.info.get('deleteTime') else ''
    rows = []
    lastDay = None
    for p in ch.posts:
        when = ts(p['createTime'])
        day = when.strftime('%d.%m.%Y')
        if day != lastDay:
            rows.append(f'<div class="day">{day}</div>')
            lastDay = day
        u = users.get(p['userId'], {'name': p['userId']})
        ava = f'{archiveRel}/avatars/{esc(u.get("name", ""))}.png'
        cls = 'post sys' if p.get('specialMsgType') else 'post'
        body = []
        root = p.get('rootPostId')
        if root:
            rp = byId.get(root)
            if rp:
                ru = users.get(rp['userId'], {'name': rp['userId']})
                body.append(f'<div class="reply">↪ <a href="#{esc(root)}">{esc(displayName(ru))}: '
                            f'{esc(snippet(rp.get("message", "")) or "[вложение]")}</a></div>')
            else:
                body.append('<div class="reply">↪ ответ в ветке</div>')
        if p.get('message'):
            body.append(f'<div class="msg">{renderMessage(p["message"])}</div>')
        files = []
        for a in p.get('attachments') or []:
            name = a.get('name', a['id'])
            stored = ch.files.get(a['id'])
            label = f'{esc(name)} ({fmtSize(a.get("byteSize", 0))})'
            if stored:
                href = f'{archiveRel}/{esc(ch.base)}--files/{esc(stored)}'
                if str(a.get('mimeType', '')).startswith('image/'):
                    files.append(f'<a href="{href}" title="{esc(name)}"><img loading="lazy" src="{href}" alt="{esc(name)}"></a>')
                else:
                    files.append(f'<a class="file" href="{href}">📎 {label}</a>')
            else:
                files.append(f'<span class="file missing">📎 {label} — не скачан</span>')
        if files:
            body.append(f'<div class="files">{"".join(files)}</div>')
        reacts = {}
        for r in p.get('reactions') or []:
            reacts.setdefault(r.get('emojiName', '?'), []).append(displayName(users.get(r.get('userId'), {'name': '?'})))
        if reacts:
            body.append('<div>' + ''.join(
                f'<span class="react" title="{esc(", ".join(who))}">{EMOJI.get(e, ":" + esc(e) + ":")} {len(who)}</span>'
                for e, who in reacts.items()) + '</div>')
        rows.append(
            f'<div class="{cls}" id="{esc(p["id"])}"><img class="ava" loading="lazy" src="{ava}" alt="" '
            f'onerror="this.style.visibility=\'hidden\'"><div class="body"><span class="who">{esc(displayName(u))}</span>'
            f'<span class="time"><a href="#{esc(p["id"])}">{when.strftime("%H:%M")}</a></span>{"".join(body)}</div></div>')
    return (f'<!doctype html><html lang="ru"><meta charset="utf-8"><title>{esc(title)}</title><style>{CSS}</style>'
            f'<header><h1>{esc(title)}</h1><div class="sub"><a href="index.html">← все каналы</a> · {kind}{archived} · '
            f'{len(ch.posts)} сообщений</div></header><main>{"".join(rows)}</main></html>')


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    archive = Path(sys.argv[1]).resolve()
    outDir = Path(sys.argv[2]).resolve() if len(sys.argv) == 3 else archive.parent / 'html'
    outDir.mkdir(parents=True, exist_ok=True)
    archiveRel = Path(os.path.relpath(archive, outDir)).as_posix()

    channels = [Channel(archive, f) for f in sorted(archive.glob('*.meta.json'))]
    allUsers = {}
    for ch in channels:
        allUsers.update(ch.users)
    me = os.environ.get('MATTERMOST_USERNAME', '')
    if not me:
        common = None
        for ch in channels:
            if ch.info.get('type') == 'Direct':
                names = {u['name'] for u in ch.users.values()}
                common = names if common is None else common & names
        me = next(iter(common), '') if common and len(common) == 1 else ''

    rows = []
    for ch in sorted(channels, key=lambda c: -(c.posts[-1]['createTime'] if c.posts else 0)):
        if not ch.posts:
            continue
        page = ch.base + '.html'
        (outDir / page).write_text(renderChannel(ch, me, archiveRel, allUsers), encoding='utf-8')
        kind = TYPE_LABEL.get(ch.info.get('type'), ch.info.get('type', ''))
        if ch.info.get('deleteTime'):
            kind += ', архив'
        nfiles = sum(len(p.get('attachments') or []) for p in ch.posts)
        rows.append(f'<tr><td><a href="{esc(page)}">{esc(ch.title(me))}</a></td><td>{kind}</td>'
                    f'<td class="n">{len(ch.posts)}</td><td class="n">{nfiles}</td>'
                    f'<td>{ts(ch.posts[0]["createTime"]):%d.%m.%Y}</td><td>{ts(ch.posts[-1]["createTime"]):%d.%m.%Y}</td></tr>')

    total = sum(len(c.posts) for c in channels)
    search = ('<script>q.oninput=()=>{const v=q.value.toLowerCase();for(const r of document.querySelectorAll("tbody tr"))'
              'r.style.display=r.textContent.toLowerCase().includes(v)?"":"none"}</script>')
    (outDir / 'index.html').write_text(
        f'<!doctype html><html lang="ru"><meta charset="utf-8"><title>Архив Mattermost</title><style>{CSS}</style>'
        f'<header><h1>Архив Mattermost</h1><div class="sub">{len(rows)} каналов · {total} сообщений · '
        f'собрано {datetime.now():%d.%m.%Y %H:%M}</div></header><main><input id="q" placeholder="Фильтр по названию…">'
        f'<table><thead><tr><th>Канал</th><th>Тип</th><th>Сообщений</th><th>Файлов</th><th>Первое</th><th>Последнее</th></tr>'
        f'</thead><tbody>{"".join(rows)}</tbody></table></main>{search}</html>', encoding='utf-8')
    print(f'{len(rows)} channel pages + index.html -> {outDir}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
