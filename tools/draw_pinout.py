"""Generate the compact connector pinout. Requires Pillow."""
from pathlib import Path
from html import escape
import os
from PIL import Image, ImageDraw, ImageFont

out=Path(__file__).resolve().parents[1]/'docs/images'
out.mkdir(parents=True,exist_ok=True)
im=Image.new('RGB',(1440,370),'white')
d=ImageDraw.Draw(im)
font=os.environ.get('WIRING_FONT',r'C:\Windows\Fonts\arial.ttf')
svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="370" viewBox="0 0 1440 370">', '<rect width="1440" height="370" fill="white"/>']
def text(x,y,s,size,color):
    f=ImageFont.truetype(font,size)
    d.text((x,y),s,font=f,fill=color,anchor='mt')
    svg.append(f'<text x="{x}" y="{y+size*0.8}" text-anchor="middle" font-family="Arial,sans-serif" font-size="{size}" fill="{color}">{escape(s)}</text>')
def rect(x,y,w,h,r,fill,stroke):
    d.rounded_rectangle((x,y,x+w,y+h),radius=r,fill=fill,outline=stroke,width=3)
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="3"/>')
red='#c13d32';gray='#617084';blue='#2265b4';green='#00866e'
top=[('A12','GND',gray),('A11','—',gray),('A10','—',gray),('A9','VCC',red),('A8','—',gray),('A7','—',gray),('A6','—',gray),('A5','GND',gray),('A4','VCC',red),('A3','RS485 A',blue),('A2','RS485 B',blue),('A1','GND',gray)]
bottom=[('B1','GND',gray),('B2','CAN H',green),('B3','CAN L',green),('B4','—',gray),('B5','GND',gray),('B6','USB D+',blue),('B7','USB D−',blue),('B8','—',gray),('B9','—',gray),('B10','—',gray),('B11','—',gray),('B12','GND',gray)]
rect(28,125,1384,120,58,'#edf1f6','#354459')
for row,py,sy,cy in [(top,83,36,143),(bottom,265,309,209)]:
    for i,(pin,sig,col) in enumerate(row):
        x=104+i*112
        text(x,py,pin,26,'#243448')
        text(x,sy,sig,23,col)
        rect(x-35,cy,70,17,3,col,col)
svg.append('</svg>')
(out/'t40-pinout.svg').write_text('\n'.join(svg),encoding='utf-8',newline='\n')
im.save(out/'t40-pinout.png')
