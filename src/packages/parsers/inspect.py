"""Local native inspection. Production invokes this only in the parser child process."""
from __future__ import annotations

import hashlib
import math
import ctypes
from pathlib import Path

DEFAULT_LIMITS = {'max_bytes':50*1024*1024,'max_pages':200,'max_pixels':40_000_000,
                  'max_text_characters':1_000_000,'max_objects':100_000,'max_page_points':20_000}


class PDFError(ValueError):
    def __init__(self, code, message=None, details=None):
        self.code, self.details = code, details or {}
        super().__init__(message or code)


def pdf_box_to_display(page, box):
    """Apply PDFium's exact CropBox/Rotate display matrix, retaining point precision."""
    import pypdfium2 as pdfium
    width,height=page.get_size();scale=1000
    left,bottom,right,top=box;points=[]
    for x,y in [(left,bottom),(left,top),(right,bottom),(right,top)]:
        dx,dy=ctypes.c_int(),ctypes.c_int()
        ok=pdfium.raw.FPDF_PageToDevice(page.raw,0,0,round(width*scale),round(height*scale),0,x,y,ctypes.byref(dx),ctypes.byref(dy))
        if not ok:raise PDFError('PDF_INVALID','Page coordinate transform failed')
        points.append((dx.value/scale,dy.value/scale))
    return [max(0,min(x for x,y in points)),max(0,min(y for x,y in points)),min(width,max(x for x,y in points)),min(height,max(y for x,y in points))]


def inspect_pdf(path, limits=None):
    from .progress import report_progress
    import pypdfium2 as pdfium
    from pypdf import PdfReader
    limits = DEFAULT_LIMITS | (limits or {})
    file = Path(path)
    if file.is_symlink() or not file.is_file():
        raise PDFError('PDF_INVALID','PDF is missing or a symlink')
    size = file.stat().st_size
    if size > limits['max_bytes']:
        raise PDFError('UPLOAD_TOO_LARGE')
    with file.open('rb') as handle:
        if not handle.read(8).startswith(b'%PDF-'):
            raise PDFError('UNSUPPORTED_FORMAT')
        handle.seek(0)
        sha = hashlib.file_digest(handle,'sha256').hexdigest()
    try:
        reader = PdfReader(file,strict=True)
        if reader.is_encrypted:
            raise PDFError('PDF_ENCRYPTED')
        if int(reader.trailer.get('/Size',0)) > limits['max_objects']:
            raise PDFError('PDF_RESOURCE_LIMIT','PDF object count exceeds limit')
        count = len(reader.pages)
        if count == 0:
            raise PDFError('PDF_INVALID','No pages')
        if count > limits['max_pages']:
            raise PDFError('PDF_PAGE_LIMIT')
        result = {'media_type':'application/pdf','byte_size':size,'sha256':sha,'page_count':count,
                  'encrypted':False,'valid':True,'pages':[], 'warnings':[]}
        pdf = pdfium.PdfDocument(file)
        try:
            total_chars = 0
            for index in range(count):
                report_progress('page_started', page=index + 1, phase='inspection')
                page = pdf[index]
                try:
                    source_page = reader.pages[index]
                    width,height = page.get_size()
                    if not all(math.isfinite(x) and 0 < x <= limits['max_page_points'] for x in (width,height)):
                        raise PDFError('PDF_RESOURCE_LIMIT','Invalid/oversized page geometry')
                    textpage = page.get_textpage()
                    try:
                        chars = textpage.count_chars()
                        total_chars += chars
                        if total_chars > limits['max_text_characters']:
                            raise PDFError('PDF_TEXT_LIMIT')
                        text = textpage.get_text_bounded()
                        rectangles = []
                        native_characters=[]
                        for char_index in range(chars):
                            cp=pdfium.raw.FPDFText_GetUnicode(textpage,char_index)
                            if not cp:continue
                            if cp>0x10ffff or 0xd800<=cp<=0xdfff:cp=0xfffd
                            cl,cb,cr,ct=textpage.get_charbox(char_index)
                            character={'index':char_index,'bbox':pdf_box_to_display(page,(cl,cb,cr,ct)),'text':chr(cp)}
                            character['font_size']=pdfium.raw.FPDFText_GetFontSize(textpage,char_index)
                            x,y=ctypes.c_double(),ctypes.c_double()
                            if pdfium.raw.FPDFText_GetCharOrigin(textpage,char_index,ctypes.byref(x),ctypes.byref(y)):
                                character['origin']=[x.value,y.value]
                            if cp == ord('?'):
                                flags=ctypes.c_int()
                                length=pdfium.raw.FPDFText_GetFontInfo(textpage,char_index,None,0,ctypes.byref(flags))
                                if 0 < length <= 1024 and 'origin' in character:
                                    font=ctypes.create_string_buffer(length)
                                    pdfium.raw.FPDFText_GetFontInfo(textpage,char_index,font,length,ctypes.byref(flags))
                                    character['font']=font.value.decode('utf-8',errors='replace')
                            native_characters.append(character)
                        # PDFium rectangle grouping provides native text coverage independently of Docling.
                        rect_count = textpage.count_rects()
                        for rect_index in range(rect_count):
                            left,bottom,right,top = textpage.get_rect(rect_index)
                            clipped = pdf_box_to_display(page,(left,bottom,right,top))
                            if clipped[0] > clipped[2] or clipped[1] > clipped[3]:
                                continue
                            rectangles.append(clipped)
                        from .glyphs import embedded_symbol_evidence, native_regions
                        symbols=embedded_symbol_evidence(source_page) if any(g.get('font') for g in native_characters) else []
                        regions,glyph_reconciliations=native_regions(native_characters,rectangles,symbol_evidence=symbols)
                        from .footnotes import native_footnote_markers
                        footnote_markers=native_footnote_markers(native_characters)
                    finally:
                        textpage.close()
                    image_areas, image_regions, graphic_regions = [], [], []
                    objects=list(page.get_objects())
                    # PDFium 153 reports un-clipped form content bounds. The
                    # PDF's own Form /BBox is a mandatory clipping boundary.
                    resources=source_page.get('/Resources',{}).get('/XObject',{})
                    form_boxes=[]
                    content=source_page.get_contents()
                    if content is not None:
                        for operands,operator in content.operations:
                            if operator!=b'Do' or not operands:continue
                            resource=resources.get(operands[0])
                            if resource:
                                resource=resource.get_object()
                                if resource.get('/Subtype')=='/Form':form_boxes.append(resource.get('/BBox'))
                    forms=[obj for obj in objects if obj.level==0 and obj.type==pdfium.raw.FPDF_PAGEOBJ_FORM]
                    form_clip={id(obj):bbox for obj,bbox in zip(forms,form_boxes)} if len(forms)==len(form_boxes) else {}
                    for obj in objects:
                        if obj.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE:
                            left,bottom,right,top = obj.get_bounds()
                            # Nested XObject bounds are local to their form. The
                            # enclosing top-level form provides page-space geometry.
                            if obj.level == 0:
                                image_areas.append(max(0,right-left)*max(0,top-bottom)/(width*height))
                                image_regions.append({'bbox':pdf_box_to_display(page,(left,bottom,right,top))})
                            metadata = obj.get_metadata()
                            if metadata.width * metadata.height > limits['max_pixels']:
                                raise PDFError('PDF_RESOURCE_LIMIT','Embedded image pixel limit exceeded')
                        elif obj.type in (pdfium.raw.FPDF_PAGEOBJ_PATH,pdfium.raw.FPDF_PAGEOBJ_FORM) and obj.level == 0:
                            left,bottom,right,top = obj.get_bounds()
                            clipping=form_clip.get(id(obj))
                            if clipping and len(clipping)==4:
                                cl,cb,cr,ct=obj.get_matrix().on_rect(*[float(v) for v in clipping])
                                left,bottom,right,top=max(left,cl),max(bottom,cb),min(right,cr),min(top,ct)
                            area=max(0,right-left)*max(0,top-bottom)/(width*height)
                            # Significant native vector regions provide independent evidence
                            # for missed figures/tables; tiny rules and full-page backgrounds
                            # do not become false body-coverage claims.
                            if .01 <= area <= .65 and min(right-left,top-bottom)>2:
                                graphic_regions.append({'bbox':pdf_box_to_display(page,(left,bottom,right,top))})
                    visible = len(''.join(text.split()))
                    # A full-page bitmap with only a heading/footer text layer is still an OCR case.
                    scan = (max(image_areas,default=0) >= .65 and visible < 150) or (visible == 0 and bool(image_areas))
                    links=[]
                    for annotation in source_page.get('/Annots',[]):
                        annotation=annotation.get_object();action=annotation.get('/A',{})
                        uri=action.get('/URI') if action else None;rect=annotation.get('/Rect')
                        if isinstance(uri,str) and len(uri)<=2048 and uri.startswith(('https://','http://')) and rect and len(rect)==4:
                            links.append({'uri':uri,'bbox':pdf_box_to_display(page,[float(v) for v in rect])})
                    result['pages'].append({'page':index+1,'page_size':[width,height],
                        'media_box':[float(x) for x in source_page.mediabox],
                        'crop_box':[float(x) for x in source_page.cropbox],
                        'rotation':int(source_page.get('/Rotate',0)) % 360,
                        'coordinate_system':'top-left-points','text_characters':visible,
                        'text_regions':regions,'glyph_reconciliations':glyph_reconciliations,'footnote_markers':footnote_markers,
                        'scan_suspected':scan,'image_area_fractions':image_areas,
                        'image_regions':image_regions,'graphic_regions':graphic_regions,'links':links})
                finally:
                    page.close()
                report_progress('page_completed', page=index + 1, phase='inspection')
        finally:
            pdf.close()
        # DOI enrichment uses existing native inspection; it does not wait for
        # the full VLM pipeline and never follows links supplied by the PDF.
        from packages.metadata.discovery import discover_doi
        metadata = dict(reader.metadata or {})
        xmp = ''
        try:
            stream = reader.trailer['/Root'].get('/Metadata')
            if stream:
                raw = stream.get_object().get_data()
                if len(raw) <= 262144: xmp = raw.decode('utf-8', errors='replace')
        except Exception:
            result['warnings'].append({'code': 'XMP_UNAVAILABLE'})
        result['doi_discovery'] = discover_doi(metadata, result['pages'], xmp=xmp)
        return result
    except PDFError:
        raise
    except Exception as exc:
        # Do not expose raw parser exceptions or document strings through the API.
        raise PDFError('PDF_INVALID','Native PDF decoder rejected the document') from exc


class PdfInspector:
    def inspect(self, local_pdf, limits=None):
        return inspect_pdf(local_pdf,limits)
