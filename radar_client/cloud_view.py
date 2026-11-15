"""Full-data canvas: drawing never silently subsamples raw points."""
import time
import numpy as np
from matplotlib.cm import ScalarMappable
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.collections import LineCollection
from matplotlib.patches import Circle
from matplotlib.ticker import MaxNLocator
from mpl_toolkits.mplot3d import Axes3D
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from occupied_contour import occupied_cells, exposed_faces, projected_boundary

SURFACE='#101820'
TEXT='#e7eff6'
MUTED='#9aafbf'
GRID='#2a3947'
ACCENT='#54d3c0'
HEIGHT_MAP=LinearSegmentedColormap.from_list('height',['#4b7bec','#53cbe4','#66dcaf','#efd879','#ef926f'])
DISTANCE_MAP=LinearSegmentedColormap.from_list('distance',['#f3b37b','#e5d989','#6cd9b2','#5aa1dc'])

def display_xyz(points):
    if not len(points):return np.empty((0,3))
    raw=np.asarray(points,dtype=float)[:,:3]
    return raw[np.isfinite(raw).all(axis=1)][:,[1,0,2]]

def live_layers(snapshot):
    frozen=snapshot.get('frozen',False)
    age=snapshot.get('udp_age')
    alive=frozen or (age is not None and age<2.5)
    ages=snapshot.get('layer_ages',{})
    history=snapshot.get('history_seconds',0)
    return {name:snapshot[name] if alive and (frozen or
            (ages.get(name) is not None and ages[name]<max(history,10 if name=='wire' else 3))) else []
            for name in ('ground','wire','pcla')}

class CloudView:
    def __init__(self,figure,range_m=10):
        self.figure=figure;self.range_m=range_m;self.zlimits=(-3,3);self.auto_fit=True
        self.mode='3D';self.color_mode='height';self.layers=dict(ground=True,pcla=True,wire=True)
        self.point_size=3;self.outline_mode='局部轮廓＋点云';self.group_radius=.3;self.height_scale=2
        self.last=None;self.signature=None;self.last_stats={}
        self.build()

    def build(self):
        fig=self.figure
        fig.clear();fig.set_facecolor(SURFACE)
        three=self.mode=='3D'
        self.ax=fig.add_axes([.02,.18,.86,.77],projection='3d' if three else None,facecolor=SURFACE)
        ax=self.ax
        if three:
            ax.view_init(elev=23,azim=-60);ax.set_proj_type('persp',focal_length=1.1)
            for axis in (ax.xaxis,ax.yaxis,ax.zaxis):
                axis.set_pane_color((.06,.09,.12,1));axis._axinfo['grid'].update(color=GRID,linewidth=.5)
            ax.set_zlabel('高度 Z / m',color=MUTED,labelpad=7)
            ax.zaxis.set_major_locator(MaxNLocator(4))
            ax.mouse_init(rotate_btn=1,pan_btn=2,zoom_btn=3)
        else:
            ax.set_aspect('equal',adjustable='box');ax.grid(color=GRID,alpha=.65)
            for spine in ax.spines.values():spine.set_color(GRID)
        ax.tick_params(colors=MUTED,labelsize=8)
        ax.set_xlabel('右侧 Y / m' if self.mode!='侧视' else '前方 X / m',color=MUTED,labelpad=9)
        ax.set_ylabel('前方 X / m' if self.mode!='侧视' else '高度 Z / m',color=MUTED,labelpad=9)
        self.map=fig.add_axes([.79,.70,.18,.23],facecolor='#0c1219')
        self.map.set_aspect('equal');self.map.tick_params(colors=MUTED,labelsize=6)
        self.map.set_title('俯视定位 / m',color=MUTED,fontsize=8,pad=6)
        for spine in self.map.spines.values():spine.set_edgecolor(GRID)
        self.scatters={};self.map_scatters={}
        for name,marker in [('ground','.'),('pcla','o'),('wire','^')]:
            args=dict(s=self.point_size,marker=marker,edgecolors='none',alpha=.8)
            self.scatters[name]=ax.scatter([],[],[],depthshade=False,**args) if three else ax.scatter([],[],**args)
            self.map_scatters[name]=self.map.scatter([],[],s=2,marker='.',edgecolors='none',alpha=.65)
        if three:ax.scatter([0],[0],[0],c=ACCENT,s=65,marker='^',depthshade=False)
        else:ax.scatter([0],[0],c=ACCENT,s=65,marker='^',zorder=9)
        self.map.scatter([0],[0],c=ACCENT,s=30,marker='^',zorder=9)
        self.rings=[];self.outline_artists=[];self.groups=[];self.last_contour=0
        self.apply_range()
        self.mapper=ScalarMappable(Normalize(*self.zlimits),HEIGHT_MAP)
        cax=fig.add_axes([.15,.085,.42,.014])
        self.colorbar=fig.colorbar(self.mapper,cax=cax,orientation='horizontal')
        self.colorbar.ax.tick_params(colors=MUTED,labelsize=7);self.colorbar.outline.set_edgecolor(GRID)
        self.colorbar.set_label('高度 Z / m · 相对雷达',color=MUTED,fontsize=8)
        self.colorbar.ax.xaxis.set_label_position('top')
        self.legend_info=fig.text(.80,.63,'原始回波全量绘制\n圆点：障碍候选\n三角：线状候选\n细点：地面回波',color=MUTED,fontsize=8,linespacing=1.6,va='top')
        self.outline_info=fig.text(.80,.40,'',color=ACCENT,fontsize=8,linespacing=1.6,va='top')
        self.info=fig.text(.02,.975,'',color=MUTED,fontsize=9,va='top')
        fn=ax.text2D if three else ax.text
        self.notice=fn(.48,.5,'等待点云数据',transform=ax.transAxes,ha='center',va='center',color='#e5c38b',fontsize=13,
                      bbox=dict(facecolor=SURFACE,edgecolor=GRID,alpha=.95,pad=12),zorder=100)
        self.signature=None
        if self.last is not None:self.update(self.last,force=True)

    def apply_range(self):
        r=self.range_m;self.ax.set_xlim(-r,r)
        self.ax.set_ylim(self.zlimits if self.mode=='侧视' else (-r,r))
        if self.mode=='3D':
            self.ax.set_zlim(self.zlimits);self.ax.set_box_aspect((2*r,2*r,(self.zlimits[1]-self.zlimits[0])*self.height_scale),zoom=1.18)
        self.map.set_xlim(-r,r);self.map.set_ylim(-r,r)
        for artist in self.rings:artist.remove()
        self.rings=[];t=np.linspace(0,2*np.pi,100)
        for radius in (r/2,r):
            circle=Circle((0,0),radius,fill=False,edgecolor='#3f5364',linewidth=.6)
            self.map.add_patch(circle);self.rings.append(circle)
            if self.mode=='3D':self.rings.extend(self.ax.plot(radius*np.cos(t),radius*np.sin(t),np.zeros_like(t),color='#314755',lw=.6,alpha=.6))
            elif self.mode=='俯视':
                circle=Circle((0,0),radius,fill=False,edgecolor='#314755',linewidth=.6)
                self.ax.add_patch(circle);self.rings.append(circle)

    def fit_all(self):
        self.auto_fit=True;self.range_m=1;self.zlimits=(-.5,.5)
        if self.last is not None:self.update(self.last,force=True)

    def set_range(self,value):
        self.auto_fit=False;self.range_m=max(.5,float(value));self.apply_range()
        if self.last is not None:self.update(self.last,force=True)

    def set_mode(self,mode):self.mode=mode;self.build()

    def set_color(self,mode,redraw=True):
        self.color_mode=mode
        if redraw and self.last is not None:self.update(self.last,force=True)

    def update(self,snapshot,force=False):
        self.last=snapshot;fresh=live_layers(snapshot)
        raw_mode=snapshot.get('cloud_source')=='sectors'
        self.legend_info.set_text('旋转扇区回波\n方位—斜距平面图\n高度未作三维重建\n零位与角度待校准' if raw_mode else '原始回波全量绘制\n圆点：障碍候选\n三角：线状候选\n细点：地面回波')
        source={k:display_xyz(v) for k,v in fresh.items()};total=sum(len(p) for p in source.values())
        enabled={k:v for k,v in source.items() if self.layers[k]}
        combined=np.concatenate(list(enabled.values())) if enabled else np.empty((0,3))
        signature=(snapshot.get('frame_total'),tuple(len(p) for p in source.values()),snapshot.get('frozen',False))
        if signature==self.signature and not force:return None
        self.signature=signature
        if len(combined):
            xy=float(np.max(np.abs(combined[:,:2])))
            zlow=float(min(0,combined[:,2].min()));zhigh=float(max(0,combined[:,2].max()))
            changed=False
            if self.auto_fit and xy>=self.range_m*.97:self.range_m=max(1,xy*1.12);changed=True
            if zlow<self.zlimits[0] or zhigh>self.zlimits[1]:
                margin=max(.25,(zhigh-zlow)*.06)
                self.zlimits=(min(self.zlimits[0],zlow-margin),max(self.zlimits[1],zhigh+margin));changed=True
            if changed:self.apply_range()
            norm=Normalize(zlow,max(zlow+.1,zhigh)) if self.color_mode=='height' else Normalize(0,max(1,float(np.linalg.norm(combined,axis=1).max())))
            if abs(norm.vmin-self.mapper.norm.vmin)>.05 or abs(norm.vmax-self.mapper.norm.vmax)>.05 or force:
                self.mapper.set_norm(norm);self.mapper.set_cmap(HEIGHT_MAP if self.color_mode=='height' else DISTANCE_MAP)
                self.colorbar.update_normal(self.mapper)
            self.colorbar.set_label('高度 Z / m · 相对雷达' if self.color_mode=='height' else '直线距离 / m',color=MUTED,fontsize=8)
        plotted=outside=hidden=0;contour_points=[]
        for name,xyz in source.items():
            if not self.layers[name]:hidden+=len(xyz);xyz=np.empty((0,3))
            inside=(np.abs(xyz[:,0])<=self.range_m)&(np.abs(xyz[:,1])<=self.range_m)
            outside+=int((~inside).sum());xyz=xyz[inside];plotted+=len(xyz)
            if name in ('pcla','wire'):contour_points.append(xyz)
            values=xyz[:,2] if self.color_mode=='height' else np.linalg.norm(xyz,axis=1)
            colors=self.mapper.to_rgba(values);scatter=self.scatters[name]
            if self.mode=='3D':scatter._offsets3d=(xyz[:,0],xyz[:,1],xyz[:,2])
            else:scatter.set_offsets(xyz[:,[1,2]] if self.mode=='侧视' else xyz[:,:2])
            scatter.set_facecolors(colors);scatter.set_sizes([self.point_size*(1.8 if name=='wire' else 1)])
            scatter.set_visible(self.outline_mode!='仅轮廓')
            self.map_scatters[name].set_offsets(xyz[:,:2]);self.map_scatters[name].set_facecolors(colors)
            self.map_scatters[name].set_visible(self.outline_mode!='仅轮廓')
        outline_source=np.concatenate(contour_points) if contour_points else np.empty((0,3))
        self.update_contour(outline_source,force or not len(outline_source))
        connected=snapshot.get('frozen') or (snapshot.get('udp_age') is not None and snapshot['udp_age']<2.5)
        self.notice.set_visible(not connected or plotted==0 or (self.outline_mode=='仅轮廓' and not len(outline_source)))
        if not connected:self.notice.set_text('等待点云链路' if snapshot.get('udp_age') is None else '点云链路中断\n当前回波已过期，等待新数据')
        elif hidden and not plotted:self.notice.set_text('图层已隐藏\n打开右侧图层开关')
        elif outside and not plotted:self.notice.set_text('点在当前视野外\n点击“显示全部”')
        else:self.notice.set_text('当前没有可显示的回波\n检查转速、图层和雷达状态')
        mode='冻结快照' if snapshot.get('frozen') else (f"最近 {snapshot.get('history_seconds',0):g} 秒累积" if snapshot.get('history_seconds') else '最新一帧')
        self.info.set_text(f'{mode}   ·   视野 ±{self.range_m:.1f} m   ·   无高度裁切'+(f'   ·   高度视觉 ×{self.height_scale:g}' if self.mode=='3D' else ''))
        if raw_mode:
            self.info.set_text(f'{mode} · 扇区方位/斜距（待校准） · 视野 ±{self.range_m:.1f} m')
            self.ax.set_xlabel('参考 Y / m（斜距投影）',color=MUTED)
            self.ax.set_ylabel('参考 X / m（斜距投影）',color=MUTED)
            if not connected:self.notice.set_text(snapshot.get('sector_status','等待扇区数据'))
        self.last_stats=dict(total=total,plotted=0 if self.outline_mode=='仅轮廓' else plotted,outside=outside,hidden=hidden,
                             latest=sum(snapshot.get('latest_counts',{}).values()),contour_only=plotted if self.outline_mode=='仅轮廓' else 0,
                             cells=getattr(self,'cell_count',0),resolution=getattr(self,'cell_size',self.group_radius))
        return self.last_stats

    def update_contour(self,xyz,force=False):
        enabled=self.outline_mode!='仅点云'
        if not enabled:xyz=np.empty((0,3))
        now=time.monotonic()
        if len(xyz) and not force and now-self.last_contour<.75:return
        self.last_contour=now
        for artist in self.outline_artists:artist.remove()
        self.outline_artists=[]
        cells,step=occupied_cells(xyz,self.group_radius,max_cells=2000)
        self.cell_count=len(cells);self.cell_size=step;self.groups=list(cells)
        if len(cells):
            if self.mode=='3D':
                faces=exposed_faces(cells,step)
                centers=np.asarray([np.asarray(face).mean(axis=0) for face in faces])
                values=centers[:,2] if self.color_mode=='height' else np.linalg.norm(centers,axis=1)
                colors=self.mapper.to_rgba(values);colors[:,3]=.15 if self.outline_mode!='仅轮廓' else .5
                poly=Poly3DCollection(faces,facecolors=colors,edgecolors=(.35,.8,.75,.25),linewidths=.25)
                self.ax.add_collection3d(poly);self.outline_artists.append(poly)
            else:
                edges=projected_boundary(cells,step,(1,2) if self.mode=='侧视' else (0,1))
                line=LineCollection(edges,colors=ACCENT,linewidths=1.0,alpha=.85)
                self.ax.add_collection(line);self.outline_artists.append(line)
            line=LineCollection(projected_boundary(cells,step),colors=ACCENT,linewidths=.55,alpha=.65)
            self.map.add_collection(line);self.outline_artists.append(line)
        self.outline_info.set_text(f'局部占据轮廓\n{len(cells):,} 个格子 · {step:.2f} m\n\n保留间隙，不跨空区连线\n格子是回波范围估计\n不是物体真实表面' if enabled else '轮廓已关闭\n所有有效原始点保留')
