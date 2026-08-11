import zipfile, sys, io
from xml.etree import ElementTree as ET

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

z = zipfile.ZipFile('report/吴昊天_阶段一第一周汇报.pptx')
slides = sorted([n for n in z.namelist() if n.startswith('ppt/slides/slide') and n.endswith('.xml')],
                key=lambda x: int(x.split('/')[-1].replace('slide','').replace('.xml','')))
print(f'幻灯片数: {len(slides)}\n')
for s in slides:
    slide_num = int(s.split('/')[-1].replace('slide','').replace('.xml',''))
    texts = [t.text for t in ET.fromstring(z.read(s)).iter('{http://schemas.openxmlformats.org/drawingml/2006/main}t') if t.text]
    print(f"=== 第{slide_num}页 ===")
    print(' '.join(texts))
    print()
