"""Generate the reference wiring diagram (SVG + PNG). Requires Pillow."""
from pathlib import Path
from html import escape
import os
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs'/'images'
OUT.mkdir(parents=True,exist_ok=True)
W,H=1600,1780
im=Image.new('RGB',(W,H),'#f4f7fb');d=ImageDraw.Draw(im)
fontpath=os.environ.get('WIRING_FONT',r'C:\Windows\Fonts\msyh.ttc')
if not Path(fontpath).exists():
    raise SystemExit('Set WIRING_FONT to a Chinese-capable TrueType/OpenType font.')
svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">', '<rect width="100%" height="100%" fill="#f4f7fb"/>']
ink='#152c44'; muted='#52667a'; red='#bb382c'; green='#087d6d'; blue='#2567bc'; gray='#667589'
def box(x,y,w,h,fill='#ffffff',stroke='#d6dfe9',r=14):
    d.rounded_rectangle((x,y,x+w,y+h),radius=r,fill=fill,outline=stroke,width=2)
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
def text(x,y,s,size=26,color=ink):
    d.text((x,y),s,font=ImageFont.truetype(fontpath,size),fill=color)
    svg.append(f'<text x="{x}" y="{y+size}" font-family="Microsoft YaHei,Noto Sans CJK SC,sans-serif" font-size="{size}" fill="{color}">{escape(s)}</text>')
def line(x1,y1,x2,y2,color=gray,width=3):
    d.line((x1,y1,x2,y2),fill=color,width=width)
    svg.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}"/>')

text(60,36,'T40 雷达 · 引脚与接线参考',46)
text(62,103,'RD2484R  /  Windows + PCAN-USB + 雷达内置 AR1021x USBWLAN',25,muted)
box(60,154,1480,104,'#fff2e9','#e7ad87')
text(82,168,'自定义 Type-C 接口：区分正反，不能用普通 USB-C 线直连电脑。',29,red)
text(82,210,'以下是来源图的针号排布，不是实物焊接面；上电前必须核对转接板针号及通断。',24)

box(60,286,1480,405)
text(84,302,'01  雷达侧针脚排列',30)
text(84,346,'按原作者 Type-C plug 图重绘；不要根据本图猜测母座、焊盘或插入方向。',24,muted)
top=[('A12','GND',gray),('A11','—',gray),('A10','—',gray),('A9','VCC',red),('A8','—',gray),('A7','—',gray),('A6','—',gray),('A5','GND',gray),('A4','VCC',red),('A3','485 A',blue),('A2','485 B',blue),('A1','GND',gray)]
bottom=[('B1','GND',gray),('B2','CAN H',green),('B3','CAN L',green),('B4','—',gray),('B5','GND',gray),('B6','USB D+',blue),('B7','USB D−',blue),('B8','—',gray),('B9','—',gray),('B10','—',gray),('B11','—',gray),('B12','GND',gray)]
box(87,437,1424,88,'#e8eef5','#9aaabb',40)
for row,y in [(top,410),(bottom,548)]:
    for i,(pin,sig,col) in enumerate(row):
        x=100+i*117
        text(x+22,y,pin,23)
        box(x+10,450 if row is top else 492,78,17,col,col,3)
        text(x+2,y-32 if row is top else y+36,sig,21,col)
text(84,638,'“—”仅表示来源未标注：保持不接，不代表已证实是空脚。RS485 本项目不接。',23,muted)

box(60,716,1480,435)
text(84,733,'02  功能接线表',30)
text(90,786,'雷达 / 转接板针脚',25,muted)
text(640,786,'连接到',25,muted)
text(1130,786,'说明',25,muted)
rows=[('A4、A9 · VCC','外部雷达电源正极','供电规格见下方',red),
      ('A1/A5/A12、B1/B5/B12 · GND','电源负极 / USB GND / CAN GND','核对实际转接板共地',gray),
      ('B2 · CAN H','USB-CAN 的 CAN H','PCAN DB9：7 脚',green),
      ('B3 · CAN L','USB-CAN 的 CAN L','PCAN DB9：2 脚',green),
      ('B6 · USB D+','电脑 USB D+（经专用转接线）','USB-A：3 脚',blue),
      ('B7 · USB D−','电脑 USB D−（经专用转接线）','USB-A：2 脚',blue)]
for i,(a,b,c,col) in enumerate(rows):
    y=836+i*48
    line(84,y-8,1515,y-8,'#e0e7ee',1)
    text(90,y,a,23,col);text(640,y,b,23);text(1130,y,c,23,muted)

box(60,1175,1480,265)
text(84,1192,'03  电脑端与供电要点',30)
text(85,1244,'USB-A：2 = D−，3 = D+，4 = GND；1 = +5V，本参考接线中不连接。',25)
text(85,1287,'不要把电脑 USB +5V 与雷达 VCC 相连；不要按标准 USB-C VBUS 位置并脚。',25,red)
text(85,1330,'PCAN-USB：DB9 7 = CAN H，2 = CAN L，3/6 = CAN GND；1/9 不给雷达供电。',24)
text(85,1373,'CAN 设置 1 Mbps。核对两端终端电阻；已有终端时不要重复并接。',24,muted)

box(60,1464,1480,164,'#eef4fc','#bdd0e6')
text(84,1480,'电源与实物核对',28)
text(84,1525,'原作者资料提到 15V；本项目此前使用 12V / 3A。两者不能互相作为额定规格证明。',24)
text(84,1567,'以设备铭牌、原厂资料与转接板标识为准；本图未对你的实际插头方向逐针实测。',24)
text(65,1653,'来源：leommxj · DJI T40 RD2484R 雷达逆向分析；PEAK · PCAN-USB User Manual §4.1。',22,muted)
text(65,1690,'针脚资料重绘 · 原图与参考链接见 docs/WIRING.md · 2026-11-15',22,muted)
svg.append('</svg>')
(OUT/'t40-wiring.svg').write_text('\n'.join(svg),encoding='utf-8',newline='\n')
im.save(OUT/'t40-wiring.png')
print(OUT/'t40-wiring.png')
