"""Assign native glyphs once and reconcile only independently proven glyphs."""
import math
import re
import unicodedata


ACCENTS={'´':'\u0301','`':'\u0300','¨':'\u0308','˘':'\u0306','ˆ':'\u0302','˜':'\u0303','˚':'\u030a','¸':'\u0327'}


def _same_font(native, embedded):
    native,embedded = str(native).lstrip('/'),str(embedded).lstrip('/')
    # PDFium may omit a subset prefix. If it supplies one, it is identity
    # evidence and must not be discarded to match a different embedded subset.
    return native == (embedded if re.match(r'^[A-Z]{6}\+', native)
                      else re.sub(r'^[A-Z]{6}\+', '', embedded))


def _text_origin(cm, tm):
    point = [tm[4]*cm[0] + tm[5]*cm[2] + cm[4], tm[4]*cm[1] + tm[5]*cm[3] + cm[5]]
    return point if all(math.isfinite(v) for v in point) else None


def _same_origin(first, second):
    return bool(first and second and len(first) == len(second) == 2
                and all(abs(a-b) <= .05 for a,b in zip(first, second)))


def _embedded_question_encoding(font):
    """Accept only the explicit, bounded Type1 encoding for byte 63."""
    from pypdf._codecs import adobe_glyphs
    if (not font or font.get('/Subtype') != '/Type1' or '/Encoding' in font
            or '/ToUnicode' in font):
        return None
    descriptor = font['/FontDescriptor']
    stream = descriptor['/FontFile']
    length = int(stream.get('/Length1', 0))
    if not 0 < length <= 1_048_576:
        return None
    header = stream.get_data()[:length].decode('ascii', errors='strict')
    header = re.sub(r'%[^\r\n]*', '', header)
    names = re.findall(r'/FontName\s+(/[^\s]+)\s+def', header)
    name = font.get('/BaseFont')
    if names != [name] or descriptor.get('/FontName') != name or header.count('/Encoding') != 1:
        return None
    encoding = re.search(r'/Encoding\s+256\s+array\s+0\s+1\s+255\s*'
        r'\{\s*1\s+index\s+exch\s+/\.notdef\s+put\s*\}\s+for'
        r'((?:\s+dup\s+\d+\s+/[\w.]+\s+put)*)\s+readonly\s+def', header)
    if not encoding:
        return None
    entries = re.findall(r'\bdup\s+(\d+)\s+(/[\w.]+)\s+put', encoding[1])
    names = [name for code,name in entries if int(code) == 63]
    if len(names) != 1:
        return None
    symbol = adobe_glyphs.get(names[0], '')
    if len(symbol) != 1 or not unicodedata.category(symbol).startswith('S'):
        return None
    return {'font': str(name), 'encoded_byte': 63, 'glyph_name': names[0], 'replacement': symbol}


def embedded_symbol_evidence(page):
    """Corroborate a singleton draw with pypdf decoding and its embedded font.

    PDFium can expose a Type1 symbol's byte as '?'. A font name or visual
    resemblance is insufficient: require the actual draw byte, a uniquely
    encoded symbolic glyph, and independently decoded text at the same origin.
    Unsupported/malformed optional evidence never prevents native inspection.
    """
    draws=[];candidates=[];fonts={}
    def operand(operator, operands, cm, tm):
        if operator not in (b'Tj', b'TJ') or not operands:
            return
        strings = [operands[0]] if operator == b'Tj' else [v for v in operands[0] if isinstance(v, (str, bytes))]
        encoded = None
        if len(strings) == 1:
            value = strings[0]
            encoded = bytes(value) if isinstance(value, bytes) else value.original_bytes
        draws.append((_text_origin(cm, tm), encoded))
    def text(value, cm, tm, font, size):
        if len(value) != 1 or not unicodedata.category(value).startswith('S'):
            return
        key = id(font)
        if key not in fonts:
            fonts[key] = _embedded_question_encoding(font)
        proof = fonts[key]
        if proof and value == proof['replacement']:
            candidates.append(dict(proof, origin=_text_origin(cm, tm)))
    try:
        page.extract_text(visitor_text=text, visitor_operand_before=operand)
    except Exception:
        return []
    return [proof for proof in candidates if proof['origin']
            and [encoded for point,encoded in draws if _same_origin(proof['origin'], point)] == [b'?']
            and sum(_same_origin(proof['origin'], other['origin']) for other in candidates) == 1]


def native_regions(glyphs,rectangles,*,symbol_evidence=()):
    glyphs=[dict(g) for g in glyphs];audit=[];removed=set()
    for proof in symbol_evidence:
        matches = [g for g in glyphs if g['text'] == '?' and g.get('font')
                   and _same_font(g['font'], proof['font'])
                   and _same_origin(g.get('origin'), proof['origin'])]
        if len(matches) != 1:
            continue
        base = matches[0]
        audit.append({'action': 'native_embedded_symbol_reconciliation', 'base': dict(base),
                      'replacement': proof['replacement'], 'evidence': dict(proof)})
        base['text'] = proof['replacement']
    for accent in glyphs:
        mark=ACCENTS.get(accent['text'])
        if not mark or mark=='\u0327':continue  # Cedillas need a separate below-baseline proof.
        a=accent['bbox'];ah=a[3]-a[1];aw=a[2]-a[0]
        choices=[]
        for base in glyphs:
            if not base['text'].isalpha() or 'LATIN' not in unicodedata.name(base['text'],''):continue
            b=base['bbox'];bh=b[3]-b[1];bw=b[2]-b[0]
            if not bh>0 or ah>.6*bh or not b[1]-.5*bh<=a[3]<=b[1]+.65*bh:continue
            if min(a[2],b[2])-max(a[0],b[0])<.5*min(aw,bw) or a[1]>=b[1]:continue
            choices.append((abs((a[0]+a[2])-(b[0]+b[2])),base))
        if not choices:continue
        choices.sort(key=lambda pair:pair[0])
        if len(choices)>1 and choices[1][0]-choices[0][0]<.25:continue
        base=choices[0][1];letter='i' if base['text']=='ı' else base['text']
        composed=unicodedata.normalize('NFC',letter+mark)
        if len(composed)!=1 or 'LATIN' not in unicodedata.name(composed,''):continue
        audit.append({'action':'native_latin_accent_composition','accent':dict(accent),'base':dict(base),'replacement':composed})
        base['text']=composed;removed.add(accent['index'])
    owned=[[] for _ in rectangles]
    for glyph in glyphs:
        if glyph['index'] in removed:continue
        b=glyph['bbox'];x,y=(b[0]+b[2])/2,(b[1]+b[3])/2
        candidates=[i for i,r in enumerate(rectangles) if r[0]-.001<=x<=r[2]+.001 and r[1]-.001<=y<=r[3]+.001]
        if candidates:
            owner=min(candidates,key=lambda i:((rectangles[i][2]-rectangles[i][0])*(rectangles[i][3]-rectangles[i][1]),i))
            owned[owner].append(glyph)
    output=[]
    for box,members in zip(rectangles,owned):
        members.sort(key=lambda g:g['index']);text=''.join(g['text'] for g in members)
        if text.strip():output.append({'bbox':box,'text':text,'native_indices':[g['index'] for g in members]})
    return output,audit


def region_text(regions):
    if regions and all(len(r.get('native_indices',[]))==len(r['text']) for r in regions):
        chars={i:c for r in regions for i,c in zip(r['native_indices'],r['text'])}
        return ''.join(chars[i] for i in sorted(chars))
    return ' '.join(r['text'] for r in regions)
