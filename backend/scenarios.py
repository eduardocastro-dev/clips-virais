"""GTA Studio original 9-scene broadcast environments.

Procedural/owned graphics only.  Exactly one physical TV is composited in the
upper half; its content is a replaceable, traceable media slot.  Presenter and
caption zones contain no fixed scenery objects or labels.
"""
from __future__ import annotations
import json
import hashlib
import math
import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from backend import core as db

W,H=1080,1920
TV_OUTER=(92,225,988,788)
TV_SCREEN=(143,291,937,733)
PRESENTER_ZONE=(160,800,920,1388)
CAPTIONS_ZONE=(65,1400,1015,1580)
FPS=30

SCENARIOS={
 'gta-news':dict(name='GTA NEWS',kind='newsroom',color='#20d9e7',other='#ed52b6',tag='AO VIVO',sfx='news_stinger'),
 'gta-theory':dict(name='GTA THEORY',kind='investigation',color='#287a7c',other='#e7a34a',tag='INVESTIGAÇÃO',sfx='riser'),
 'gta-comparison':dict(name='GTA COMPARISON',kind='showroom',color='#379af4',other='#f59346',tag='COMPARAÇÃO',sfx='whoosh'),
 'gta-cinematic':dict(name='GTA CINEMATIC',kind='cinema',color='#248f91',other='#e8a05f',tag='CINEMA',sfx='cinematic'),
 'gta-facts':dict(name='GTA FACTS',kind='arcade',color='#80e5c6',other='#e94ee8',tag='FATOS',sfx='arcade_pop'),
 'gta-reaction':dict(name='GTA REACTION',kind='gaming_room',color='#e351cf',other='#36d9f4',tag='REAÇÃO',sfx='hit'),
 'gta-radar-viral':dict(name='RADAR GTA 6',kind='radar',color='#78e89c',other='#40b7c8',tag='VIRAL',sfx='radar_ping'),
 'gta-detail-breakdown':dict(name='GTA EM DETALHES',kind='analysis',color='#77b3da',other='#e7b36d',tag='ANÁLISE',sfx='shutter'),
 'gta-hype-reaction':dict(name='VICE CITY TALK',kind='radio',color='#fa619a',other='#f8a351',tag='NO AR',sfx='radio_stinger'),
}


def _rgba(hex_color: str, opacity=255):
    v=hex_color.lstrip('#')
    return tuple(int(v[i:i+2],16) for i in (0,2,4))+(opacity,)


def _font(size,bold=False):
    name='DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'
    location='/usr/share/fonts/truetype/dejavu/'+name
    try:return ImageFont.truetype(location,size)
    except OSError:return ImageFont.load_default()


def _text(d,xy,value,font,color,anchor=None):
    d.text(xy,str(value),font=font,fill=color,anchor=anchor,stroke_width=1,
           stroke_fill=(4,11,20,185))


def template_for(template: str) -> dict | None:
    return SCENARIOS.get(template)


def geometry() -> dict:
    return {'canvas':[W,H],'tv_outer':list(TV_OUTER),
            'tv_screen':list(TV_SCREEN),'presenter_zone':list(PRESENTER_ZONE),
            'captions_zone':list(CAPTIONS_ZONE),'frame_rate':FPS}


def _plate(style:dict) -> Image.Image:
    img=Image.new('RGBA',(W,H),(9,16,27,255))
    d=ImageDraw.Draw(img,'RGBA')
    c=_rgba(style['color']);q=_rgba(style['other'])
    for y in range(0,H,6):
        f=y/H
        d.rectangle((0,y,W,y+5),fill=(int(10+c[0]*.045+f*5),
                                     int(13+c[1]*.045),int(24+c[2]*.055),255))
    # Panels, windows and decorative accents cannot enter the presenter zone.
    d.rectangle((0,0,W,215),fill=(8,15,25,255))
    d.rectangle((0,1590,W,H),fill=(10,17,26,255))
    for side in (0,1):
        x=26 if side==0 else 1014
        d.rounded_rectangle((x,235,x+39,1370),radius=15,
                            fill=c[:3]+(26,),outline=c[:3]+(140,),width=4)
        for j in range(15):
            a=240+j*71
            if a<800 or a>=1388:
                d.line((x+8,a,x+31,a),fill=q[:3]+(100,),width=2)
    mode=style['kind']
    # Top-only visual storytelling. Never draw a prop or subtitle at 800..1580.
    if mode in ('newsroom','radio'):
        for x in range(80,1060,110):
            top=96+int(35*math.sin(x/85))
            d.rectangle((x,top,x+56,212),fill=(33,63,85,110))
            for yy in range(top+16,209,26):
                d.rectangle((x+9,yy,x+15,yy+11),fill=q[:3]+(70,))
        if mode=='newsroom':
            d.line((0,157,1080,157),fill=q[:3]+(210,),width=5)
        else:
            d.ellipse((240,-240,840,270),fill=q[:3]+(80,))
    if mode=='investigation':
        for x in (105,870):
            d.rounded_rectangle((x,40,x+95,210),radius=8,fill=(85,58,38,220),
                                outline=q[:3]+(140,),width=3)
            for j in range(4):
                yy=65+j*31
                d.line((x+10,yy,x+70,yy+17),fill=(208,65,61,160),width=2)
        d.line((530,0,530,120),fill=q[:3]+(150,),width=4)
        d.ellipse((490,105,570,165),fill=q[:3]+(115,))
    if mode=='showroom':
        d.polygon([(0,0),(520,0),(520,210),(0,210)],fill=c[:3]+(45,))
        d.polygon([(560,0),(1080,0),(1080,210),(560,210)],fill=q[:3]+(45,))
    if mode=='cinema':
        for side in (0,1):
            x0=0 if side==0 else 930
            for j in range(5):
                d.polygon([(x0+j*22,0),(x0+j*22+42,0),(x0+j*22+34,210),
                           (x0+j*22,210)],fill=(99,31,48,80+j*17))
    if mode=='arcade':
        for x in (115,905):
            for j in range(3):
                y=45+j*53
                d.rounded_rectangle((x,y,x+55,y+31),radius=8,
                                    fill=q[:3]+(70,),outline=c[:3]+(210,),width=3)
    if mode=='gaming_room':
        for x in (145,870):
            d.line((x,30,x,195),fill=c[:3]+(230,),width=10)
            d.line((x+25,30,x+25,195),fill=q[:3]+(180,),width=4)
    if mode=='radar':
        cx,cy=145,120
        for rad in (33,58,82):
            d.ellipse((cx-rad,cy-rad,cx+rad,cy+rad),outline=c[:3]+(145,),width=3)
        d.line((cx,cy,cx+64,cy-48),fill=c[:3]+(225,),width=4)
    if mode=='analysis':
        for x in (130,900):
            d.rectangle((x,43,x+45,207),outline=c[:3]+(180,),width=3)
            for y in range(55,207,21):
                d.line((x+8,y,x+36,y),fill=q[:3]+(150,),width=2)
    # Floor bands, progress counters and lower thirds live below subtitles.
    d.line((0,1592,W,1592),fill=c[:3]+(215,),width=5)
    for n in range(7):
        d.rectangle((60+n*146,1740,140+n*146,1750+n%3*13),fill=q[:3]+(75,))
    d.rounded_rectangle((78,1640,1000,1720),radius=18,
                        fill=(13,26,42,235),outline=c[:3]+(165,),width=3)
    _text(d,(105,1665),style['name'],_font(33,True),(239,247,255,255))
    _text(d,(980,1667),'GTA STUDIO',_font(19,True),c,anchor='ra')
    if mode=='comparison':_text(d,(855,1812),'VS',_font(62,True),q)
    elif mode=='radar':_text(d,(850,1820),'VIRAL',_font(37,True),c)
    elif mode=='facts':_text(d,(850,1820),'FATO #',_font(31,True),c)
    elif mode=='analysis':_text(d,(820,1820),'DETALHE',_font(27,True),c)
    elif mode=='radio':_text(d,(830,1820),'NO AR',_font(30,True),q)
    elif mode=='newsroom':_text(d,(820,1820),'URGENTE',_font(27,True),q)
    return img


def _bezel(style:dict,source_label:str='',date_label:str='',preview=False,glow_color=None):
    overlay=Image.new('RGBA',(W,H),(0,0,0,0))
    d=ImageDraw.Draw(overlay,'RGBA')
    col=_rgba(style['color'])
    if glow_color is not None:
        r,g,b=(int(v) for v in glow_color)
        r,g,b=(max(0,min(255,v)) for v in (r,g,b))
        # Light spilling below the TV is allowed through the presenter zone;
        # there are deliberately no opaque objects or text in that region.
        for inset,alpha in ((0,24),(18,34),(36,48)):
            d.rounded_rectangle((92-inset,225-inset,988+inset,788+inset),
                                radius=38+inset,outline=(r,g,b,alpha),width=13)
        d.rectangle((170,792,910,1350),fill=(r,g,b,7))
    x0,y0,x1,y1=TV_OUTER
    d.rounded_rectangle((x0,y0,x1,y1),radius=29,outline=col[:3]+(235,),width=17)
    d.rounded_rectangle((x0+12,y0+12,x1-12,y1-12),radius=21,
                        outline=(9,15,23,255),width=26)
    sx0,sy0,sx1,sy1=TV_SCREEN
    d.rectangle((sx0-7,sy0-8,sx1+7,sy1+8),outline=(10,14,20,255),width=14)
    d.line((350,y1+7,730,y1+7),fill=col[:3]+(225,),width=6)
    # Channel/source label is drawn INSIDE the TV, never on top of presenter.
    text=(source_label or 'GTA STUDIO').strip()[:32].upper()
    if date_label:text+=' · '+date_label[:12]
    d.rounded_rectangle((sx0+13,sy1-58,sx1-16,sy1-15),radius=7,
                        fill=(7,13,22,215))
    _text(d,(sx0+26,sy1-48),'FONTE: '+text,_font(20,True),(232,243,250,255))
    if preview:
        # Visible ONLY on the review preview. It is never a publishable deliverable.
        d.rounded_rectangle((115,96,965,154),radius=11,fill=(95,35,38,230))
        _text(d,(540,112),'PRÉVIA PRIVADA · DIREITOS PENDENTES',_font(25,True),
              (255,239,235,255),anchor='mt')
    return overlay


def build_layers(template:str,work:Path,*,source_label='',date_label='',preview=False,glow_color=None):
    info=template_for(template)
    if not info:return None
    work.mkdir(parents=True,exist_ok=True)
    name=re.sub(r'[^A-Za-z0-9_-]','',template)
    plate=work/(name+'-plate.png')
    version=hashlib.sha256(repr((source_label,date_label,preview,glow_color)).encode()).hexdigest()[:12]
    frame=work/(name+'-frame-'+version+'.png')
    if not plate.is_file():_plate(info).save(plate)
    _bezel(info,source_label,date_label,preview,glow_color=glow_color).save(frame)
    return {'plate':plate,'bezel':frame,'tv_screen':TV_SCREEN,
            'presenter_zone':PRESENTER_ZONE,'caption_zone':CAPTIONS_ZONE,
            'template':template,'kind':info['kind'],'sfx':info['sfx']}


def select_beats(transcript, duration:float):
    """Only aligned, actually measured word start times qualify as scene cues."""
    words=(transcript or {}).get('words') or []
    hits=[]
    for row in words:
        try:t=float(row['start'])
        except (ValueError,TypeError,KeyError):continue
        if 0.15<=t<=duration-.25 and (not hits or t-hits[-1]>=1.5):
            hits.append(round(t,3))
    return hits
