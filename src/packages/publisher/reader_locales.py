"""Authored reader UI messages, frozen with reader-v15 publications.

The translation target selects this catalog at publication time. Browser language
and reading preferences never change a saved artifact's language. Unknown source
diagnostics and document content are evidence, not translation keys.
"""
from __future__ import annotations

import json
import re

from packages.translation.languages import language_name


SUPPORTED_READER_LOCALES = ('zh-Hans', 'en', 'zh-Hant', 'ja', 'ko', 'fr', 'de', 'es')

# Each row is Simplified Chinese, English, Traditional Chinese, Japanese, Korean,
# French, German and Spanish. Full messages keep interpolation order localizable.
_ROWS = (
    ('双语章节', 'Bilingual sections', '雙語章節', '対訳の章', '대역 섹션', 'Sections bilingues', 'Zweisprachige Abschnitte', 'Secciones bilingües'),
    ('原 PDF 图像', 'Original PDF image', '原 PDF 圖像', '元の PDF 画像', '원본 PDF 이미지', 'Image du PDF original', 'Bild aus dem Original-PDF', 'Imagen del PDF original'),
    ('对照图暂不可用，打开原 PDF 查看', 'Comparison image unavailable; open the original PDF', '對照圖暫不可用，開啟原 PDF 查看', '比較画像を表示できません。元の PDF を開いてください', '비교 이미지를 사용할 수 없습니다. 원본 PDF를 여세요', 'Image de comparaison indisponible ; ouvrir le PDF original', 'Vergleichsbild nicht verfügbar; Original-PDF öffnen', 'Imagen de comparación no disponible; abrir el PDF original'),
    ('对照图暂不可用；本次导出未包含原 PDF。', 'Comparison image unavailable; this export does not include the original PDF.', '對照圖暫不可用；本次匯出未包含原 PDF。', '比較画像を表示できません。このエクスポートには元の PDF が含まれていません。', '비교 이미지를 사용할 수 없습니다. 이 내보내기에는 원본 PDF가 포함되지 않았습니다.', 'Image de comparaison indisponible ; cette exportation ne contient pas le PDF original.', 'Vergleichsbild nicht verfügbar; dieser Export enthält das Original-PDF nicht.', 'Imagen de comparación no disponible; esta exportación no incluye el PDF original.'),
    ('显示整页', 'Full page', '顯示整頁', 'ページ全体', '전체 페이지', 'Page entière', 'Ganze Seite', 'Página completa'),
    ('显示对应区域', 'Matching region', '顯示對應區域', '対応する範囲', '해당 영역', 'Zone correspondante', 'Zugehöriger Bereich', 'Región correspondiente'),
    ('查看原文 · 第 {page} 页 · {scope}', 'View original · Page {page} · {scope}', '查看原文 · 第 {page} 頁 · {scope}', '原文を表示 · {page} ページ · {scope}', '원문 보기 · {page}페이지 · {scope}', 'Voir l’original · Page {page} · {scope}', 'Original ansehen · Seite {page} · {scope}', 'Ver original · Página {page} · {scope}'),
    ('此格暂无译文，保留原文：', 'No translation for this cell; original text: ', '此格暫無譯文，保留原文：', 'このセルは未翻訳です。原文：', '이 셀의 번역이 없습니다. 원문: ', 'Cellule non traduite ; texte original : ', 'Diese Zelle ist nicht übersetzt; Originaltext: ', 'Esta celda no tiene traducción; texto original: '),
    ('原文', 'Original', '原文', '原文', '원문', 'Original', 'Original', 'Original'),
    ('译文', 'Translation', '譯文', '訳文', '번역', 'Traduction', 'Übersetzung', 'Traducción'),
    ('DRAFT — 此块译文未完成', 'DRAFT — This block is not fully translated', '草稿 — 此區塊譯文未完成', '下書き — このブロックは未翻訳です', '초안 — 이 블록의 번역이 완료되지 않았습니다', 'BROUILLON — Ce bloc n’est pas entièrement traduit', 'ENTWURF — Dieser Block ist nicht vollständig übersetzt', 'BORRADOR — Este bloque no está completamente traducido'),
    ('此段尚无译文，以下保留原文', 'This paragraph is not translated; the original is shown below', '此段尚無譯文，以下保留原文', 'この段落は未翻訳です。以下に原文を表示します', '이 문단의 번역이 없어 아래에 원문을 표시합니다', 'Ce paragraphe n’est pas traduit ; l’original figure ci-dessous', 'Dieser Absatz ist nicht übersetzt; das Original steht unten', 'Este párrafo no está traducido; se muestra el original a continuación'),
    ('此处保留原页图像，请查看原文对照。', 'The original page image is retained; see the original comparison.', '此處保留原頁圖像，請查看原文對照。', '元のページ画像を保持しています。原文との比較をご覧ください。', '원본 페이지 이미지가 보존되어 있습니다. 원문 비교를 확인하세요.', 'L’image de la page originale est conservée ; consultez la comparaison.', 'Das Originalseitenbild bleibt erhalten; siehe Originalvergleich.', 'Se conserva la imagen de la página original; consulte la comparación.'),
    ('模型辅助信息 · {kind}', 'Model-assisted information · {kind}', '模型輔助資訊 · {kind}', 'モデルの補助情報 · {kind}', '모델 보조 정보 · {kind}', 'Informations du modèle · {kind}', 'Modellinformationen · {kind}', 'Información auxiliar del modelo · {kind}'),
    ('内容提示（{count} 项）', 'Content notices ({count})', '內容提示（{count} 項）', '内容に関する注意（{count} 件）', '콘텐츠 알림 ({count}개)', 'Remarques sur le contenu ({count})', 'Inhaltshinweise ({count})', 'Avisos de contenido ({count})'),
    ('脚注、参考文献与内容提示', 'Footnotes, references and content notices', '註腳、參考文獻與內容提示', '脚注、参考文献、内容に関する注意', '각주, 참고 문헌 및 콘텐츠 알림', 'Notes de bas de page, références et remarques', 'Fußnoten, Literatur und Inhaltshinweise', 'Notas al pie, referencias y avisos de contenido'),
    ('内容提示与原文对照', 'Content notices and original comparison', '內容提示與原文對照', '内容に関する注意と原文の比較', '콘텐츠 알림 및 원문 비교', 'Remarques et comparaison avec l’original', 'Inhaltshinweise und Originalvergleich', 'Avisos de contenido y comparación con el original'),
    ('脚注 · {label}', 'Footnote · {label}', '註腳 · {label}', '脚注 · {label}', '각주 · {label}', 'Note de bas de page · {label}', 'Fußnote · {label}', 'Nota al pie · {label}'),
    ('返回引用位置', 'Return to citation', '返回引用位置', '引用元に戻る', '인용 위치로 돌아가기', 'Revenir à la citation', 'Zur Textstelle zurück', 'Volver a la cita'),
    ('在脚注列表中查看', 'View in footnotes', '在註腳列表中查看', '脚注一覧で表示', '각주 목록에서 보기', 'Voir dans les notes de bas de page', 'In den Fußnoten ansehen', 'Ver en las notas al pie'),
    ('（原文，暂无译文）', '(Original; not translated)', '（原文，暫無譯文）', '（原文・未翻訳）', '(원문, 번역 없음)', '(Original ; non traduit)', '(Original; nicht übersetzt)', '(Original; sin traducción)'),
    ('原文在上 · 译文在下 · 数值保留原文', 'Original above · Translation below · Numbers unchanged', '原文在上 · 譯文在下 · 數值保留原文', '上段：原文 · 下段：訳文 · 数値は原文を保持', '위: 원문 · 아래: 번역 · 숫자는 원문 유지', 'Original en haut · Traduction en bas · Nombres inchangés', 'Original oben · Übersetzung unten · Zahlen unverändert', 'Original arriba · Traducción abajo · Números sin cambios'),
    ('查看原 PDF 表格', 'View original PDF table', '查看原 PDF 表格', '元の PDF の表を表示', '원본 PDF 표 보기', 'Voir le tableau du PDF original', 'Tabelle im Original-PDF ansehen', 'Ver tabla del PDF original'),
    ('识别文字（仅供辅助对照）', 'Recognized text (for comparison only)', '辨識文字（僅供輔助對照）', '認識されたテキスト（比較用）', '인식된 텍스트 (비교 참고용)', 'Texte reconnu (à titre de comparaison)', 'Erkannter Text (nur zum Vergleich)', 'Texto reconocido (solo como referencia)'),
    ('查看原PDF裁图', 'View original PDF crop', '查看原 PDF 裁圖', '元の PDF の切り抜きを表示', '원본 PDF 잘라낸 이미지 보기', 'Voir l’extrait du PDF original', 'Ausschnitt des Original-PDF ansehen', 'Ver recorte del PDF original'),
    ('本地识别的 LaTeX 表示。', 'Locally recognized LaTeX representation.', '本機辨識的 LaTeX 表示。', 'ローカルで認識された LaTeX 表現です。', '로컬에서 인식한 LaTeX 표현입니다.', 'Représentation LaTeX reconnue localement.', 'Lokal erkannte LaTeX-Darstellung.', 'Representación LaTeX reconocida localmente.'),
    ('保留原式，未推测或重写数学表示。', 'Original formula retained; mathematical notation was not inferred or rewritten.', '保留原式，未推測或重寫數學表示。', '元の数式を保持しています。数式表現の推測や書き換えは行っていません。', '원래 수식을 보존하며 수학 표현을 추측하거나 다시 쓰지 않았습니다.', 'Formule originale conservée ; la notation n’a été ni déduite ni réécrite.', 'Originalformel beibehalten; mathematische Notation weder erschlossen noch umgeschrieben.', 'Se conserva la fórmula original; no se ha inferido ni reescrito la notación.'),
    ('查看参考文献原页', 'View original reference pages', '查看參考文獻原頁', '参考文献の元ページを表示', '참고 문헌 원본 페이지 보기', 'Voir les pages originales des références', 'Originalseiten der Literatur ansehen', 'Ver páginas originales de las referencias'),
    ('参考文献', 'References', '參考文獻', '参考文献', '참고 문헌', 'Références', 'Literatur', 'Referencias'),
    ('脚注', 'Footnotes', '註腳', '脚注', '각주', 'Notes de bas de page', 'Fußnoten', 'Notas al pie'),
    ('原文 PDF', 'Original PDF', '原文 PDF', '原文 PDF', '원본 PDF', 'PDF original', 'Original-PDF', 'PDF original'),
    ('DRAFT — 未完成草稿，缺失 {count} 块译文', 'DRAFT — Incomplete; untranslated blocks: {count}', '草稿 — 未完成，缺少 {count} 個區塊的譯文', '下書き — 未完了。未翻訳のブロック：{count}', '초안 — 미완료, 번역되지 않은 블록: {count}개', 'BROUILLON — Incomplet ; blocs non traduits : {count}', 'ENTWURF — Unvollständig; nicht übersetzte Blöcke: {count}', 'BORRADOR — Incompleto; bloques sin traducir: {count}'),
    ('DRAFT — 标题译文未完成', 'DRAFT — Title translation incomplete', '草稿 — 標題譯文未完成', '下書き — タイトルの翻訳が未完了', '초안 — 제목 번역 미완료', 'BROUILLON — Traduction du titre incomplète', 'ENTWURF — Titelübersetzung unvollständig', 'BORRADOR — Traducción del título incompleta'),
    ('数字', 'Numbers', '數字', '数値', '숫자', 'Nombres', 'Zahlen', 'Números'),
    ('标题', 'Heading', '標題', '見出し', '제목', 'Titre', 'Überschrift', 'Título'),
    ('段落', 'Paragraph', '段落', '段落', '문단', 'Paragraphe', 'Absatz', 'Párrafo'),
    ('表格', 'Table', '表格', '表', '표', 'Tableau', 'Tabelle', 'Tabla'),
    ('表格单元格', 'Table cell', '表格儲存格', '表のセル', '표 셀', 'Cellule de tableau', 'Tabellenzelle', 'Celda de tabla'),
    ('代码', 'Code', '程式碼', 'コード', '코드', 'Code', 'Code', 'Código'),
    ('公式', 'Formula', '公式', '数式', '수식', 'Formule', 'Formel', 'Fórmula'),
    ('图片', 'Image', '圖片', '画像', '이미지', 'Image', 'Bild', 'Imagen'),
    ('图注', 'Caption', '圖說', 'キャプション', '캡션', 'Légende', 'Bildunterschrift', 'Pie de figura'),
    ('列表', 'List', '清單', 'リスト', '목록', 'Liste', 'Liste', 'Lista'),
    ('分组', 'Group', '群組', 'グループ', '그룹', 'Groupe', 'Gruppe', 'Grupo'),
    ('第 {page} 页 · 重要提示', 'Page {page} · Important notice', '第 {page} 頁 · 重要提示', '{page} ページ · 重要な注意', '{page}페이지 · 중요 알림', 'Page {page} · Remarque importante', 'Seite {page} · Wichtiger Hinweis', 'Página {page} · Aviso importante'),
    ('第 {page} 页 · 一般提示', 'Page {page} · General notice', '第 {page} 頁 · 一般提示', '{page} ページ · 一般的な注意', '{page}페이지 · 일반 알림', 'Page {page} · Remarque générale', 'Seite {page} · Allgemeiner Hinweis', 'Página {page} · Aviso general'),
    ('查看说明（{count} 项）', 'View details ({count})', '查看說明（{count} 項）', '詳細を表示（{count} 件）', '설명 보기 ({count}개)', 'Voir les détails ({count})', 'Details ansehen ({count})', 'Ver detalles ({count})'),
    ('内容提示', 'Content notices', '內容提示', '内容に関する注意', '콘텐츠 알림', 'Remarques sur le contenu', 'Inhaltshinweise', 'Avisos de contenido'),
    ('提示不影响阅读、发布或导出。暂无译文的段落已明确标注并保留原文。', 'Notices do not block reading, publication or export. Untranslated paragraphs are clearly marked and retain the original text.', '提示不影響閱讀、發布或匯出。暫無譯文的段落已明確標註並保留原文。', '注意は閲覧、公開、エクスポートを妨げません。未翻訳の段落は明示され、原文が保持されています。', '알림은 읽기, 게시 또는 내보내기를 차단하지 않습니다. 번역되지 않은 문단은 명확히 표시되며 원문이 보존됩니다.', 'Les remarques n’empêchent ni la lecture, ni la publication, ni l’exportation. Les paragraphes non traduits sont signalés et conservent le texte original.', 'Hinweise verhindern weder Lesen noch Veröffentlichen oder Exportieren. Nicht übersetzte Absätze sind gekennzeichnet und behalten den Originaltext.', 'Los avisos no impiden la lectura, publicación o exportación. Los párrafos sin traducir están señalados y conservan el texto original.'),
    ('重要性', 'Severity', '重要性', '重要度', '중요도', 'Importance', 'Wichtigkeit', 'Importancia'),
    ('全部', 'All', '全部', 'すべて', '전체', 'Tout', 'Alle', 'Todos'),
    ('重要', 'Important', '重要', '重要', '중요', 'Importante', 'Wichtig', 'Importante'),
    ('一般', 'General', '一般', '一般', '일반', 'Générale', 'Allgemein', 'General'),
    ('页码', 'Page', '頁碼', 'ページ', '페이지', 'Page', 'Seite', 'Página'),
    ('全部页', 'All pages', '全部頁', 'すべてのページ', '모든 페이지', 'Toutes les pages', 'Alle Seiten', 'Todas las páginas'),
    ('类型', 'Type', '類型', '種類', '유형', 'Type', 'Typ', 'Tipo'),
    ('全部类型', 'All types', '全部類型', 'すべての種類', '모든 유형', 'Tous les types', 'Alle Typen', 'Todos los tipos'),
    ('此筛选下没有提示。', 'No notices match these filters.', '此篩選條件下沒有提示。', 'この条件に一致する注意はありません。', '이 필터에 해당하는 알림이 없습니다.', 'Aucune remarque ne correspond aux filtres.', 'Keine Hinweise für diese Filter.', 'No hay avisos que coincidan con estos filtros.'),
    ('未发现需要提示的内容差异。', 'No content differences requiring attention were found.', '未發現需要提示的內容差異。', '注意が必要な内容の相違は見つかりませんでした。', '주의가 필요한 콘텐츠 차이가 발견되지 않았습니다.', 'Aucune différence de contenu nécessitant une remarque n’a été trouvée.', 'Keine erwähnenswerten Inhaltsunterschiede gefunden.', 'No se encontraron diferencias de contenido que requieran atención.'),
    ('内容提示 · {count} 块', 'Content notices · Blocks: {count}', '內容提示 · {count} 個區塊', '内容に関する注意 · {count} ブロック', '콘텐츠 알림 · {count}개 블록', 'Remarques sur le contenu · Blocs : {count}', 'Inhaltshinweise · Blöcke: {count}', 'Avisos de contenido · Bloques: {count}'),
    ('减小字号', 'Decrease font size', '縮小字級', '文字を小さくする', '글꼴 크기 줄이기', 'Réduire la taille du texte', 'Schrift verkleinern', 'Reducir tamaño de letra'),
    ('增大字号', 'Increase font size', '放大字級', '文字を大きくする', '글꼴 크기 늘리기', 'Agrandir la taille du texte', 'Schrift vergrößern', 'Aumentar tamaño de letra'),
    ('字体与字号', 'Font and text size', '字型與字級', 'フォントと文字サイズ', '글꼴 및 글자 크기', 'Police et taille du texte', 'Schriftart und Schriftgröße', 'Fuente y tamaño de texto'),
    ('字体', 'Font', '字型', 'フォント', '글꼴', 'Police', 'Schriftart', 'Fuente'),
    ('衬线', 'Serif', '襯線', 'セリフ', '세리프', 'Avec empattement', 'Serifenschrift', 'Con serifa'),
    ('无衬线', 'Sans serif', '無襯線', 'サンセリフ', '산세리프', 'Sans empattement', 'Serifenlos', 'Sin serifa'),
    ('等宽', 'Monospace', '等寬', '等幅', '고정폭', 'Chasse fixe', 'Nichtproportional', 'Monoespaciada'),
    ('默认（MiSans）', 'Default (MiSans)', '預設（MiSans）', '既定（MiSans）', '기본값 (MiSans)', 'Par défaut (MiSans)', 'Standard (MiSans)', 'Predeterminada (MiSans)'),
    ('MiSans 已内置；其他选项使用本机字体。', 'MiSans is bundled; other options use locally installed fonts.', 'MiSans 已內建；其他選項使用本機字型。', 'MiSans は同梱されています。その他の項目は端末のフォントを使用します。', 'MiSans는 내장되어 있으며 다른 옵션은 기기에 설치된 글꼴을 사용합니다.', 'MiSans est incluse ; les autres options utilisent les polices locales.', 'MiSans ist enthalten; andere Optionen verwenden lokal installierte Schriftarten.', 'MiSans está incluida; las demás opciones usan fuentes instaladas localmente.'),
    ('方正宋体', 'FangZheng Song', '方正宋體', '方正宋体', 'FangZheng Song', 'FangZheng Song', 'FangZheng Song', 'FangZheng Song'),
    ('方正黑体', 'FangZheng Hei', '方正黑體', '方正黒体', 'FangZheng Hei', 'FangZheng Hei', 'FangZheng Hei', 'FangZheng Hei'),
    ('思源宋体', 'Source Han Serif', '思源宋體', '源ノ明朝', '본명조', 'Source Han Serif', 'Source Han Serif', 'Source Han Serif'),
    ('思源黑体', 'Source Han Sans', '思源黑體', '源ノ角ゴシック', '본고딕', 'Source Han Sans', 'Source Han Sans', 'Source Han Sans'),
    ('鸿蒙黑体', 'HarmonyOS Sans', '鴻蒙黑體', 'HarmonyOS Sans', 'HarmonyOS Sans', 'HarmonyOS Sans', 'HarmonyOS Sans', 'HarmonyOS Sans'),
    ('代码字体', 'Code font', '程式碼字型', 'コードのフォント', '코드 글꼴', 'Police du code', 'Codeschrift', 'Fuente del código'),
    ('JetBrains Mono 已内置；其他选项使用本机字体。', 'JetBrains Mono is bundled; other options use locally installed fonts.', 'JetBrains Mono 已內建；其他選項使用本機字型。', 'JetBrains Mono は同梱されています。その他の項目は端末のフォントを使用します。', 'JetBrains Mono는 내장되어 있으며 다른 옵션은 기기에 설치된 글꼴을 사용합니다.', 'JetBrains Mono est incluse ; les autres options utilisent les polices locales.', 'JetBrains Mono ist enthalten; andere Optionen verwenden lokal installierte Schriftarten.', 'JetBrains Mono está incluida; las demás opciones usan fuentes instaladas localmente.'),
    ('JetBrains Mono（默认）', 'JetBrains Mono (default)', 'JetBrains Mono（預設）', 'JetBrains Mono（既定）', 'JetBrains Mono (기본값)', 'JetBrains Mono (par défaut)', 'JetBrains Mono (Standard)', 'JetBrains Mono (predeterminada)'),
    ('系统等宽', 'System monospace', '系統等寬', 'システムの等幅フォント', '시스템 고정폭', 'Chasse fixe du système', 'System-Monospace', 'Monoespaciada del sistema'),
    ('行距', 'Line spacing', '行距', '行間', '줄 간격', 'Interligne', 'Zeilenabstand', 'Interlineado'),
    ('{value} 倍', '{value}×', '{value} 倍', '{value} 倍', '{value}배', '{value}×', '{value}×', '{value}×'),
    ('{value} 倍（默认）', '{value}× (default)', '{value} 倍（預設）', '{value} 倍（既定）', '{value}배 (기본값)', '{value}× (par défaut)', '{value}× (Standard)', '{value}× (predeterminado)'),
    ('主题', 'Theme', '主題', 'テーマ', '테마', 'Thème', 'Design', 'Tema'),
    ('跟随系统', 'System', '跟隨系統', 'システムに合わせる', '시스템 설정', 'Système', 'System', 'Sistema'),
    ('浅色', 'Light', '淺色', 'ライト', '밝게', 'Clair', 'Hell', 'Claro'),
    ('深色', 'Dark', '深色', 'ダーク', '어둡게', 'Sombre', 'Dunkel', 'Oscuro'),
    ('本页使用 MiSans 与 JetBrains Mono 字体。', 'This page uses MiSans and JetBrains Mono.', '本頁使用 MiSans 與 JetBrains Mono 字型。', 'このページでは MiSans と JetBrains Mono を使用しています。', '이 페이지는 MiSans 및 JetBrains Mono 글꼴을 사용합니다.', 'Cette page utilise MiSans et JetBrains Mono.', 'Diese Seite verwendet MiSans und JetBrains Mono.', 'Esta página utiliza MiSans y JetBrains Mono.'),
    ('{font} 字体许可', '{font} font license', '{font} 字型授權', '{font} フォントライセンス', '{font} 글꼴 라이선스', 'Licence de la police {font}', 'Schriftlizenz für {font}', 'Licencia de la fuente {font}'),
    ('返回文库', 'Return to library', '返回文庫', 'ライブラリに戻る', '라이브러리로 돌아가기', 'Revenir à la bibliothèque', 'Zur Bibliothek zurück', 'Volver a la biblioteca'),
    ('返回文档', 'Return to document', '返回文件', '文書に戻る', '문서로 돌아가기', 'Revenir au document', 'Zum Dokument zurück', 'Volver al documento'),
    ('返回搜索结果', 'Return to search results', '返回搜尋結果', '検索結果に戻る', '검색 결과로 돌아가기', 'Revenir aux résultats de recherche', 'Zu den Suchergebnissen zurück', 'Volver a los resultados de búsqueda'),
    ('阅读设置', 'Reading settings', '閱讀設定', '閲覧設定', '읽기 설정', 'Paramètres de lecture', 'Leseeinstellungen', 'Ajustes de lectura'),
    ('双语', 'Bilingual', '雙語', '対訳', '대역', 'Bilingue', 'Zweisprachig', 'Bilingüe'),
    ('对照文库 · {source} / {target}', 'Bilingual library · {source} / {target}', '對照文庫 · {source} / {target}', '対訳ライブラリ · {source} / {target}', '대역 라이브러리 · {source} / {target}', 'Bibliothèque bilingue · {source} / {target}', 'Zweisprachige Bibliothek · {source} / {target}', 'Biblioteca bilingüe · {source} / {target}'),
    ('浏览器存储不可用；正文仍可完整阅读。', 'Browser storage is unavailable; the full text is still readable.', '瀏覽器儲存空間不可用；正文仍可完整閱讀。', 'ブラウザーのストレージを利用できません。本文はすべて閲覧できます。', '브라우저 저장소를 사용할 수 없지만 본문은 모두 읽을 수 있습니다.', 'Le stockage du navigateur est indisponible ; le texte reste entièrement lisible.', 'Browserspeicher nicht verfügbar; der gesamte Text bleibt lesbar.', 'El almacenamiento del navegador no está disponible; el texto completo sigue siendo legible.'),
    ('文章目录', 'Article contents', '文章目錄', '記事の目次', '문서 목차', 'Sommaire de l’article', 'Inhaltsverzeichnis des Artikels', 'Contenido del artículo'),
    ('目录', 'Contents', '目錄', '目次', '목차', 'Sommaire', 'Inhalt', 'Contenido'),
    ('此公式暂不能排版，保留识别文字供原文对照。', 'This formula cannot be typeset; recognized text is retained for comparison.', '此公式暫時無法排版，保留辨識文字供原文對照。', 'この数式を組版できません。比較用に認識されたテキストを保持しています。', '이 수식을 조판할 수 없어 원문 비교용 인식 텍스트를 유지합니다.', 'Cette formule ne peut pas être mise en forme ; le texte reconnu est conservé pour comparaison.', 'Diese Formel kann nicht gesetzt werden; erkannter Text bleibt zum Vergleich erhalten.', 'No se puede componer esta fórmula; se conserva el texto reconocido para comparar.'),
    ('{font} · 已内置，可离线使用。', '{font} · Bundled and available offline.', '{font} · 已內建，可離線使用。', '{font} · 同梱済みでオフラインでも使用できます。', '{font} · 내장되어 오프라인에서도 사용할 수 있습니다.', '{font} · Incluse et disponible hors ligne.', '{font} · Enthalten und offline verfügbar.', '{font} · Incluida y disponible sin conexión.'),
    ('{font} · 使用本机字体；未安装时使用备用字体。', '{font} · Uses a local font, with a fallback if not installed.', '{font} · 使用本機字型；未安裝時使用備用字型。', '{font} · 端末のフォントを使用します。未インストールの場合は代替フォントを使用します。', '{font} · 기기의 글꼴을 사용하며 설치되지 않았다면 대체 글꼴을 사용합니다.', '{font} · Police locale ; une police de remplacement est utilisée si elle n’est pas installée.', '{font} · Lokale Schriftart; falls nicht installiert, wird eine Ersatzschrift verwendet.', '{font} · Usa una fuente local; si no está instalada, se usa una alternativa.'),
    ('参考文献详情', 'Reference details', '參考文獻詳細資訊', '参考文献の詳細', '참고 문헌 상세 정보', 'Détails de la référence', 'Literaturdetails', 'Detalles de la referencia'),
    ('参考文献 · {citation}', 'Reference · {citation}', '參考文獻 · {citation}', '参考文献 · {citation}', '참고 문헌 · {citation}', 'Référence · {citation}', 'Literatur · {citation}', 'Referencia · {citation}'),
    ('关闭参考文献', 'Close reference', '關閉參考文獻', '参考文献を閉じる', '참고 문헌 닫기', 'Fermer la référence', 'Literatur schließen', 'Cerrar referencia'),
    ('在参考文献列表中查看', 'View in references', '在參考文獻列表中查看', '参考文献一覧で表示', '참고 문헌 목록에서 보기', 'Voir dans les références', 'Im Literaturverzeichnis ansehen', 'Ver en las referencias'),
    ('来源为保存的原始 PDF。机器检查不等同于人工确认；公式和代码按声明保留。', 'Based on the saved original PDF. Automated checks do not constitute human confirmation; formulas and code are retained as declared.', '來源為儲存的原始 PDF。機器檢查不等同於人工確認；公式和程式碼按聲明保留。', '保存済みの元の PDF に基づいています。自動チェックは人による確認を意味しません。数式とコードは宣言どおり保持されます。', '저장된 원본 PDF를 기반으로 합니다. 자동 검사는 사람의 확인을 의미하지 않으며 수식과 코드는 선언된 대로 보존됩니다.', 'Basé sur le PDF original sauvegardé. Les vérifications automatiques ne constituent pas une validation humaine ; formules et code sont conservés comme indiqué.', 'Grundlage ist das gespeicherte Original-PDF. Automatische Prüfungen ersetzen keine menschliche Bestätigung; Formeln und Code bleiben wie angegeben erhalten.', 'Basado en el PDF original guardado. Las comprobaciones automáticas no equivalen a confirmación humana; las fórmulas y el código se conservan según lo indicado.'),
    ('此段未得到可靠译文，保留原文或原图。', 'No reliable translation was obtained for this paragraph; the original text or image is retained.', '此段未得到可靠譯文，保留原文或原圖。', 'この段落の信頼できる訳文を取得できなかったため、原文または元画像を保持しています。', '이 문단의 신뢰할 수 있는 번역을 얻지 못해 원문 또는 원본 이미지를 유지합니다.', 'Aucune traduction fiable n’a été obtenue pour ce paragraphe ; le texte ou l’image d’origine est conservé.', 'Für diesen Absatz liegt keine zuverlässige Übersetzung vor; Originaltext oder Originalbild bleiben erhalten.', 'No se obtuvo una traducción fiable de este párrafo; se conserva el texto o la imagen original.'),
    ('简体中文', 'Simplified Chinese', '簡體中文', '簡体字中国語', '중국어 간체', 'Chinois simplifié', 'Vereinfachtes Chinesisch', 'Chino simplificado'),
    ('繁體中文', 'Traditional Chinese', '繁體中文', '繁体字中国語', '중국어 번체', 'Chinois traditionnel', 'Traditionelles Chinesisch', 'Chino tradicional'),
    ('英语', 'English', '英語', '英語', '영어', 'Anglais', 'Englisch', 'Inglés'),
    ('日语', 'Japanese', '日語', '日本語', '일본어', 'Japonais', 'Japanisch', 'Japonés'),
    ('韩语', 'Korean', '韓語', '韓国語', '한국어', 'Coréen', 'Koreanisch', 'Coreano'),
    ('法语', 'French', '法語', 'フランス語', '프랑스어', 'Français', 'Französisch', 'Francés'),
    ('德语', 'German', '德語', 'ドイツ語', '독일어', 'Allemand', 'Deutsch', 'Alemán'),
    ('西班牙语', 'Spanish', '西班牙語', 'スペイン語', '스페인어', 'Espagnol', 'Spanisch', 'Español'),
    ('自动识别', 'Detected automatically', '自動辨識', '自動検出', '자동 감지', 'Détection automatique', 'Automatisch erkannt', 'Detección automática'),
)

_DIAGNOSTIC_ROWS = (
    ('此段暂无译文，保留原文供阅读。', 'This paragraph is not translated; the original text is retained for reading.', '此段暫無譯文，保留原文供閱讀。', 'この段落は未翻訳です。閲覧用に原文を保持しています。', '이 문단의 번역이 없어 읽을 수 있도록 원문을 유지합니다.', 'Ce paragraphe n’est pas traduit ; le texte original est conservé pour la lecture.', 'Dieser Absatz ist nicht übersetzt; der Originaltext bleibt zum Lesen erhalten.', 'Este párrafo no está traducido; se conserva el texto original para su lectura.'),
    ('此段译文无法安全展示，已保留原文。', 'This translation cannot be displayed safely; the original text is retained.', '此段譯文無法安全顯示，已保留原文。', 'この訳文を安全に表示できないため、原文を保持しています。', '이 번역을 안전하게 표시할 수 없어 원문을 유지합니다.', 'Cette traduction ne peut pas être affichée de manière sûre ; l’original est conservé.', 'Diese Übersetzung kann nicht sicher angezeigt werden; das Original bleibt erhalten.', 'Esta traducción no se puede mostrar de forma segura; se conserva el original.'),
    ('译文中的数字与原文存在差异，可查看原 PDF 对照。', 'Numbers differ between the translation and original; compare with the original PDF.', '譯文中的數字與原文存在差異，可查看原 PDF 對照。', '訳文と原文の数値が異なります。元の PDF と比較できます。', '번역의 숫자가 원문과 다릅니다. 원본 PDF와 비교할 수 있습니다.', 'Les nombres de la traduction diffèrent de l’original ; comparez avec le PDF original.', 'Zahlen in Übersetzung und Original unterscheiden sich; vergleichen Sie das Original-PDF.', 'Los números de la traducción difieren del original; compárelos con el PDF original.'),
    ('译文出现原文和术语表中没有的其他语言文字，可对照原文检查。', 'The translation contains scripts not found in the original or glossary; compare with the original.', '譯文出現原文和術語表中沒有的其他語言文字，可對照原文檢查。', '訳文に原文や用語集にない文字体系が含まれています。原文と比較して確認できます。', '번역에 원문과 용어집에 없는 문자 체계가 포함되어 있습니다. 원문과 비교하세요.', 'La traduction contient des écritures absentes de l’original et du glossaire ; comparez avec l’original.', 'Die Übersetzung enthält Schriftsysteme, die weder im Original noch im Glossar vorkommen; vergleichen Sie das Original.', 'La traducción contiene escrituras ausentes del original y del glosario; compárela con el original.'),
    ('公式、数字或引用的识别结果存在差异。', 'Recognition differs for formulas, numbers or citations.', '公式、數字或引用的辨識結果存在差異。', '数式、数値、引用の認識結果に相違があります。', '수식, 숫자 또는 인용의 인식 결과에 차이가 있습니다.', 'La reconnaissance des formules, nombres ou citations présente des différences.', 'Erkennungsergebnisse für Formeln, Zahlen oder Zitate unterscheiden sich.', 'Hay diferencias en el reconocimiento de fórmulas, números o citas.'),
    ('此段包含条件、否定或数量关系，可按需对照原文。', 'This paragraph contains conditions, negation or quantities; compare with the original if needed.', '此段包含條件、否定或數量關係，可按需對照原文。', 'この段落には条件、否定、数量関係が含まれます。必要に応じて原文と比較してください。', '이 문단에는 조건, 부정 또는 수량 관계가 포함되어 있습니다. 필요하면 원문과 비교하세요.', 'Ce paragraphe contient des conditions, négations ou quantités ; comparez avec l’original si nécessaire.', 'Dieser Absatz enthält Bedingungen, Verneinungen oder Mengenbeziehungen; bei Bedarf mit dem Original vergleichen.', 'Este párrafo contiene condiciones, negaciones o cantidades; compárelo con el original si lo necesita.'),
    ('此段用词与术语表不一致。', 'The wording in this paragraph does not match the glossary.', '此段用詞與術語表不一致。', 'この段落の用語が用語集と一致しません。', '이 문단의 용어가 용어집과 일치하지 않습니다.', 'La terminologie de ce paragraphe ne correspond pas au glossaire.', 'Die Wortwahl dieses Absatzes entspricht nicht dem Glossar.', 'La terminología de este párrafo no coincide con el glosario.'),
    ('可考虑使用术语表中的推荐用词。', 'Consider using the preferred glossary terms.', '可考慮使用術語表中的建議用詞。', '用語集の推奨用語の使用を検討してください。', '용어집의 권장 용어 사용을 고려하세요.', 'Vous pouvez utiliser les termes recommandés du glossaire.', 'Die empfohlenen Glossarbegriffe können verwendet werden.', 'Puede utilizar los términos recomendados del glosario.'),
    ('此段出现术语表中不建议使用的词。', 'This paragraph contains terms discouraged by the glossary.', '此段出現術語表中不建議使用的詞。', 'この段落には用語集で非推奨の用語が含まれています。', '이 문단에는 용어집에서 권장하지 않는 용어가 있습니다.', 'Ce paragraphe contient des termes déconseillés par le glossaire.', 'Dieser Absatz enthält im Glossar nicht empfohlene Begriffe.', 'Este párrafo contiene términos desaconsejados por el glosario.'),
    ('部分内容无法按原结构展示，生成时将使用安全替代内容。', 'Some content cannot retain its original structure; safe fallback content will be used.', '部分內容無法按原結構顯示，產生時將使用安全替代內容。', '一部の内容を元の構造で表示できないため、安全な代替内容を使用します。', '일부 콘텐츠를 원래 구조로 표시할 수 없어 안전한 대체 콘텐츠를 사용합니다.', 'Certains contenus ne peuvent pas conserver leur structure ; un contenu de remplacement sûr sera utilisé.', 'Einige Inhalte können nicht in der ursprünglichen Struktur dargestellt werden; sichere Ersatzinhalte werden verwendet.', 'Parte del contenido no puede conservar su estructura original; se usará contenido alternativo seguro.'),
    ('辅助语义检查尚未完成，已有译文可继续使用。', 'The supplementary semantic check is incomplete; existing translations remain usable.', '輔助語義檢查尚未完成，已有譯文可繼續使用。', '補助的な意味チェックは未完了ですが、既存の訳文は利用できます。', '보조 의미 검사가 완료되지 않았지만 기존 번역은 계속 사용할 수 있습니다.', 'La vérification sémantique complémentaire est incomplète ; les traductions existantes restent utilisables.', 'Die ergänzende semantische Prüfung ist unvollständig; vorhandene Übersetzungen bleiben nutzbar.', 'La comprobación semántica complementaria está incompleta; las traducciones existentes siguen disponibles.'),
    ('检查未完成，已有内容仍可阅读和导出。', 'The check is incomplete; existing content can still be read and exported.', '檢查未完成，已有內容仍可閱讀和匯出。', 'チェックは未完了ですが、既存の内容は閲覧・エクスポートできます。', '검사가 완료되지 않았지만 기존 콘텐츠는 읽고 내보낼 수 있습니다.', 'La vérification est incomplète ; le contenu reste lisible et exportable.', 'Die Prüfung ist unvollständig; vorhandene Inhalte bleiben lesbar und exportierbar.', 'La comprobación está incompleta; el contenido se puede leer y exportar.'),
    ('原图资源暂不可用，可打开原 PDF 对照。', 'The original image is unavailable; open the original PDF for comparison.', '原圖資源暫不可用，可開啟原 PDF 對照。', '元画像を利用できません。元の PDF を開いて比較できます。', '원본 이미지를 사용할 수 없습니다. 원본 PDF를 열어 비교하세요.', 'L’image originale est indisponible ; ouvrez le PDF original pour comparer.', 'Das Originalbild ist nicht verfügbar; öffnen Sie zum Vergleich das Original-PDF.', 'La imagen original no está disponible; abra el PDF original para comparar.'),
    ('此段有内容差异，可按需对照原文。', 'This paragraph contains differences; compare with the original if needed.', '此段有內容差異，可按需對照原文。', 'この段落には内容の相違があります。必要に応じて原文と比較してください。', '이 문단에는 내용 차이가 있습니다. 필요하면 원문과 비교하세요.', 'Ce paragraphe présente des différences ; comparez avec l’original si nécessaire.', 'Dieser Absatz enthält Abweichungen; bei Bedarf mit dem Original vergleichen.', 'Este párrafo presenta diferencias; compárelo con el original si lo necesita.'),
    ('{notice} 已记录核对说明：{reason}', '{notice} Review note recorded: {reason}', '{notice} 已記錄核對說明：{reason}', '{notice} 確認メモ：{reason}', '{notice} 검토 메모: {reason}', '{notice} Note de vérification enregistrée : {reason}', '{notice} Prüfvermerk gespeichert: {reason}', '{notice} Nota de revisión registrada: {reason}'),
    ('检查未完成，已有内容仍可阅读', 'The check is incomplete; existing content remains readable', '檢查未完成，已有內容仍可閱讀', 'チェックは未完了ですが、既存の内容は閲覧できます', '검사가 완료되지 않았지만 기존 콘텐츠는 읽을 수 있습니다', 'Vérification incomplète ; le contenu reste lisible', 'Prüfung unvollständig; vorhandene Inhalte bleiben lesbar', 'Comprobación incompleta; el contenido sigue siendo legible'),
    ('文字排版与原 PDF 有细微差异', 'Text layout differs slightly from the original PDF', '文字排版與原 PDF 有細微差異', '文字のレイアウトが元の PDF とわずかに異なります', '텍스트 배치가 원본 PDF와 약간 다릅니다', 'La mise en page du texte diffère légèrement du PDF original', 'Textlayout weicht geringfügig vom Original-PDF ab', 'La disposición del texto difiere ligeramente del PDF original'),
    ('数字与原 PDF 可能不同', 'Numbers may differ from the original PDF', '數字與原 PDF 可能不同', '数値が元の PDF と異なる可能性があります', '숫자가 원본 PDF와 다를 수 있습니다', 'Les nombres peuvent différer du PDF original', 'Zahlen können vom Original-PDF abweichen', 'Los números pueden diferir del PDF original'),
    ('表格内容与原 PDF 可能不同', 'Table contents may differ from the original PDF', '表格內容與原 PDF 可能不同', '表の内容が元の PDF と異なる可能性があります', '표 내용이 원본 PDF와 다를 수 있습니다', 'Le contenu des tableaux peut différer du PDF original', 'Tabelleninhalte können vom Original-PDF abweichen', 'El contenido de las tablas puede diferir del PDF original'),
    ('公式保留原图对照', 'Original formula image retained for comparison', '公式保留原圖對照', '比較用に数式の元画像を保持しています', '비교를 위해 수식의 원본 이미지를 유지합니다', 'Image originale de la formule conservée pour comparaison', 'Originalbild der Formel zum Vergleich erhalten', 'Se conserva la imagen original de la fórmula para comparar'),
    ('代码保留原图对照', 'Original code image retained for comparison', '程式碼保留原圖對照', '比較用にコードの元画像を保持しています', '비교를 위해 코드의 원본 이미지를 유지합니다', 'Image originale du code conservée pour comparaison', 'Originalbild des Codes zum Vergleich erhalten', 'Se conserva la imagen original del código para comparar'),
    ('可能存在重复内容', 'Possible duplicate content', '可能存在重複內容', '内容が重複している可能性があります', '중복 콘텐츠가 있을 수 있습니다', 'Contenu potentiellement dupliqué', 'Möglicherweise doppelte Inhalte', 'Posible contenido duplicado'),
    ('部分内容与原 PDF 不一致', 'Some content differs from the original PDF', '部分內容與原 PDF 不一致', '一部の内容が元の PDF と一致しません', '일부 콘텐츠가 원본 PDF와 일치하지 않습니다', 'Certains contenus diffèrent du PDF original', 'Einige Inhalte weichen vom Original-PDF ab', 'Parte del contenido difiere del PDF original'),
    ('第 {page} 页文字未完整提取', 'Text extraction is incomplete on page {page}', '第 {page} 頁文字未完整擷取', '{page} ページのテキスト抽出が不完全です', '{page}페이지의 텍스트 추출이 불완전합니다', 'Extraction du texte incomplète à la page {page}', 'Textextraktion auf Seite {page} unvollständig', 'Extracción de texto incompleta en la página {page}'),
)

MESSAGES = {locale: {row[0]: row[index] for row in _ROWS + _DIAGNOSTIC_ROWS}
            for index, locale in enumerate(SUPPORTED_READER_LOCALES)}
_DIAGNOSTIC_KEYS = {row[0] for row in _DIAGNOSTIC_ROWS if '{' not in row[0]} | {
    '来源为保存的原始 PDF。机器检查不等同于人工确认；公式和代码按声明保留。',
    '此段未得到可靠译文，保留原文或原图。',
}


def resolve_reader_locale(target_language):
    """Match a target locale, preserving explicit Chinese scripts over regions."""
    parts = str(target_language or '').replace('_', '-').lower().split('-')
    base = parts[0]
    if base == 'zh':
        # Stop at a Unicode/private-use extension: its subtags are not regions.
        core = []
        for part in parts[1:]:
            if len(part) == 1:
                break
            core.append(part)
        if 'hant' in core:
            return 'zh-Hant'
        if 'hans' in core:
            return 'zh-Hans'
        return 'zh-Hant' if any(region in core for region in ('tw', 'hk', 'mo')) else 'zh-Hans'
    return base if base in MESSAGES else 'en'


def reader_messages(target_language):
    """Return a fresh dictionary for a resolved target locale."""
    return dict(MESSAGES[resolve_reader_locale(target_language)])


def translate(locale, key, **values):
    message = MESSAGES[resolve_reader_locale(locale)].get(key, key)
    return re.sub(r'\{([A-Za-z][A-Za-z0-9_]*)\}',
                  lambda match: str(values.get(match[1], match[0])), message)


def reader_language_name(language, locale):
    """Localize supported names while retaining native names for other languages."""
    base = str(language or '').split('-')[0].lower()
    if base in {'auto', 'und', 'none', ''}:
        return translate(locale, '自动识别')
    names = {'zh-Hans': '简体中文', 'zh-Hant': '繁體中文', 'en': '英语',
             'ja': '日语', 'ko': '韩语', 'fr': '法语', 'de': '德语', 'es': '西班牙语'}
    if base not in {'zh', 'en', 'ja', 'ko', 'fr', 'de', 'es'}:
        return language_name(language)
    name = translate(locale, names[resolve_reader_locale(language)])
    # The label must not discard a translation's script, regional or variant tag.
    return name if language in {base, resolve_reader_locale(language)} else f'{name} ({language})'


def translate_diagnostic(locale, value):
    """Translate only known system prose; never interpret user/evidence suffixes."""
    if value in _DIAGNOSTIC_KEYS:
        return translate(locale, value)
    notice, separator, reason = value.partition(' 已记录核对说明：')
    if separator and notice in _DIAGNOSTIC_KEYS:
        return translate(locale, '{notice} 已记录核对说明：{reason}',
                         notice=translate(locale, notice), reason=reason)
    missing_page = re.fullmatch(r'第 ([1-9][0-9]*) 页文字未完整提取', value)
    if missing_page:
        return translate(locale, '第 {page} 页文字未完整提取', page=missing_page[1])
    return value


def reader_messages_json(locale):
    """Inert script data: never allow translated text to terminate its element."""
    payload = json.dumps({'locale': resolve_reader_locale(locale), 'messages': reader_messages(locale)},
                         ensure_ascii=False, separators=(',', ':'))
    return (payload.replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
            .replace('\u2028', '\\u2028').replace('\u2029', '\\u2029'))
