"""Read the supplied workbook without executing macros or changing it."""
import json
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

def extract(path):
    with zipfile.ZipFile(path) as z:
        strings = [''.join(x.itertext()) for x in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        rels = {x.attrib['Id']: x.attrib['Target'] for x in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        sheets, catalog = {}, []
        for s in ET.fromstring(z.read('xl/workbook.xml')).find('m:sheets', NS):
            target = rels[s.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
            root = ET.fromstring(z.read(target.lstrip('/') if target.startswith('/') else 'xl/' + target))
            cells = {}
            for c in root.findall('.//m:sheetData/m:row/m:c', NS):
                v = c.findtext('m:v', default='', namespaces=NS)
                if c.attrib.get('t') == 's':
                    v = strings[int(v)]
                cells[c.attrib['r']] = v
            sheets[s.attrib['name']] = cells
            catalog.append({'name': s.attrib['name'], 'hidden': s.attrib.get('state') == 'hidden'})
        base = sheets['Т.О']
        cables = []
        for r in range(2, 10):
            c = sheets['кВ']
            cables.append({'id': str(r-1), 'direction': c.get(f'A{r}', ''), 'brand': c.get(f'B{r}', ''), 'section': c.get(f'C{r}', ''), **{key: float(c.get(f'{col}{r}') or 0) for key, col in [('ground','D'), ('hdd','E'), ('pipe','F'), ('entry','G')]}})
        dates = []
        import re
        def date(v):
            m = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', v)
            return f'{m[3]}-{m[2]}-{m[1]}' if m else ''
        for r in range(2,21):
            c = sheets['DATE']
            if not c.get(f'G{r}'): continue
            name = c.get(f'E{r}') if c.get(f'E{r}') not in ('—', '', None) else c.get(f'F{r}', '').replace('•','').strip()
            dates.append({'id': str(r), 'name': name or f'Без названия (DATE, строка {r})', 'start': date(c.get(f'G{r}', '')), 'end': date(c.get(f'H{r}', '')), 'note': 'Не предусмотрено' if c.get(f'G{r}') == 'НЕТ' else ('Уточните название этапа по исходной книге' if not name else '')})
        materials = []
        c = sheets['АВК']
        for r in range(2,25):
            if c.get(f'C{r}') and c[f'C{r}'] != '0':
                materials.append({'id': str(r), 'name': c[f'C{r}'], 'manufacturer': c.get(f'E{r}', ''), 'quantity': c.get(f'G{r}', ''), 'passport': c.get(f'D{r}', ''), 'status': 'review'})
        return {'id':'dubninskaya', 'revision':1, 'name':'Дубнинская, 73Б', 'address':base.get('B6',''), 'description':base.get('B4',''), 'projectCode':base.get('B7',''), 'customer':base.get('B1',''), 'contractor':base.get('B2',''), 'subcontractor':base.get('B3',''), 'owner':'Не назначен', 'status':'В работе', 'labExpiry':'2025-12-16', 'cables':cables, 'dates':dates, 'materials':materials, 'catalog':catalog, 'notes':[], 'source':Path(path).name}

if __name__ == '__main__':
    print(json.dumps(extract(sys.argv[1]), ensure_ascii=False, indent=2))
