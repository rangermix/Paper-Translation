"""Assign native glyphs once and compose only geometrically proven Latin accents."""
import unicodedata


ACCENTS={'´':'\u0301','`':'\u0300','¨':'\u0308','˘':'\u0306','ˆ':'\u0302','˜':'\u0303','˚':'\u030a','¸':'\u0327'}


def native_regions(glyphs,rectangles):
    glyphs=[dict(g) for g in glyphs];audit=[];removed=set()
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
