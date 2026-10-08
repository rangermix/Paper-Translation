"""Reader v12 content with independent theme, text and code font preferences."""
from packages.paths import ROOT
from .reader_v12 import esc, render_html as render_content


def render_html(ir, asset_paths, *, include_source=False):
    page = render_content(ir, asset_paths, include_source=include_source)
    page = page.replace(b"; style-src", b"; font-src 'self' data:; style-src", 1)
    page = page.replace('<option value="default">默认</option>'.encode('utf-8'),
        '<option value="default">默认（MiSans）</option>'.encode('utf-8'), 1)
    previous = '<button data-action="theme">切换主题</button>'.encode('utf-8')
    control = ('<label class="font-picker code-font-picker">代码字体'
        '<select data-code-font-select title="JetBrains Mono 已内置；其他选项使用本机字体。">'
        '<option value="default">JetBrains Mono（默认）</option>'
        '<option value="fira-code">Fira Code</option>'
        '<option value="cascadia-code">Cascadia Code</option>'
        '<option value="source-code-pro">Source Code Pro</option>'
        '<option value="ibm-plex-mono">IBM Plex Mono</option>'
        '<option value="consolas">Consolas</option>'
        '<option value="menlo">Menlo</option>'
        '<option value="monospace">系统等宽</option></select></label>'
        '<label class="spacing-picker">行距<select data-line-height-select>'
        '<option value="1.4">1.4 倍</option><option value="1.72" selected>1.72 倍（默认）</option>'
        '<option value="2">2 倍</option><option value="2.4">2.4 倍</option></select></label>'
        '<label class="theme-picker">主题<select data-theme-select>'
        '<option value="system">跟随系统</option><option value="light">浅色</option>'
        '<option value="dark">深色</option></select></label>').encode('utf-8')
    page = page.replace(previous, control, 1)
    page = page.replace('title="使用本机字体；未安装时使用备用字体。"'.encode('utf-8'),
        'title="MiSans 已内置；其他选项使用本机字体。"'.encode('utf-8'), 1)
    licenses = ''.join('<details><summary>' + label + ' 字体许可</summary><pre>'
        + esc((ROOT / 'res/vendor/reader-fonts' / filename).read_text('utf-8')) + '</pre></details>'
        for label, filename in [('MiSans', 'MiSans-LICENSE.txt'), ('JetBrains Mono', 'JetBrainsMono-OFL.txt')])
    notice = '<footer class="reader-font-notice">本页使用 MiSans 与 JetBrains Mono 字体。' + licenses + '</footer>'
    return page.replace(b'</body>', notice.encode('utf-8') + b'</body>', 1)
