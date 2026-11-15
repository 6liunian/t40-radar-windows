"""Desktop workbench: large canvas, inspectable data counts, persistent motor bar."""
import csv
import math
import os
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from cloud_view import CloudView

BG='#0b1118';PANEL='#101820';EDGE='#263644';TEXT='#e7eff6';MUTED='#97aabd';ACCENT='#54d3c0'


class WorkspaceLayout:
    def _button(self,parent,label,command,accent=False):
        return tk.Button(parent,text=label,command=command,relief='flat',bd=0,padx=12,pady=7,
                         bg='#21554f' if accent else '#1b2835',fg=TEXT,activebackground='#304858',
                         activeforeground=TEXT,font=('Microsoft YaHei UI',9),cursor='hand2')

    def _build_layout(self):
        self.frozen_snapshot=None;self.last_live_snapshot=None;self._last_draw=0;self.draw_seconds=.1
        self.root.title('T40 点云工作台 · 0.5.2')
        self.root.geometry('1480x920');self.root.minsize(1080,700)
        self.root.configure(bg=BG)
        if not os.environ.get('RADAR_TEST_WINDOW'):
            self.root.after_idle(lambda:self.root.state('zoomed') if not self.closing else None)
        self.root.bind('<F11>',self._fullscreen)
        self.root.bind('<Escape>',lambda e:self.root.attributes('-fullscreen',False))
        header=tk.Frame(self.root,bg=BG);header.pack(fill='x',padx=16,pady=(10,8))
        tk.Label(header,text='T40  /  点云工作台',bg=BG,fg=TEXT,font=('Microsoft YaHei UI',16,'bold')).pack(side='left')
        self.header_status=tk.Label(header,text='正在连接',bg='#1b2835',fg=MUTED,padx=12,pady=5,font=('Microsoft YaHei UI',9))
        self.header_status.pack(side='left',padx=20)
        self._button(header,'导出点云',self._export_cloud).pack(side='right',padx=(5,0))
        self._button(header,'F11 全屏',self._fullscreen).pack(side='right',padx=5)
        self._button(header,'收起 / 展开侧栏',self._toggle_sidebar).pack(side='right',padx=5)

        footer=tk.Frame(self.root,bg=PANEL,highlightbackground=EDGE,highlightthickness=1)
        footer.pack(side='bottom',fill='x',padx=12,pady=(5,10))
        self._motor_bar(footer)
        self.footer_note=tk.Label(self.root,text='左键旋转 · 中键平移 · 滚轮缩放 · 显示全部可恢复完整视野',
                                  bg=BG,fg=MUTED,font=('Microsoft YaHei UI',8),anchor='w')
        self.footer_note.pack(side='bottom',fill='x',padx=18,pady=(2,3))

        tools=tk.Frame(self.root,bg=PANEL);tools.pack(fill='x',padx=12,pady=(0,6))
        self.view_buttons={}
        for name in ('3D','俯视','侧视'):
            button=self._button(tools,name,lambda mode=name:self._change_view(mode),name=='3D')
            button.pack(side='left',padx=3,pady=5);self.view_buttons[name]=button
        self._button(tools,'显示全部',self._fit_cloud,True).pack(side='left',padx=(16,4))
        self._button(tools,'复位视角',lambda:self._change_view('3D')).pack(side='left',padx=4)
        self.freeze_button=self._button(tools,'冻结观察',self._freeze_cloud)
        self.freeze_button.pack(side='left',padx=(16,4))
        self._button(tools,'清除累积',self._clear_history).pack(side='left',padx=4)
        self.view_hint=tk.Label(tools,text='全量数据 / 自动范围',bg=PANEL,fg=MUTED,font=('Microsoft YaHei UI',8))
        self.view_hint.pack(side='right',padx=12)

        self.body=tk.Frame(self.root,bg=BG);self.body.pack(fill='both',expand=True,padx=12)
        self.body.grid_columnconfigure(0,weight=1);self.body.grid_rowconfigure(0,weight=1)
        scene=tk.Frame(self.body,bg=PANEL,highlightbackground=EDGE,highlightthickness=1)
        scene.grid(row=0,column=0,sticky='nsew',padx=(0,8))
        counters=tk.Frame(scene,bg=PANEL);counters.pack(fill='x',padx=14,pady=(10,0))
        self.count_labels={}
        for key,label in [('drawn','实际绘制'),('available','当前可用'),('latest','最新帧合计'),('excluded','未显示')]:
            box=tk.Frame(counters,bg=PANEL);box.pack(side='left',fill='x',expand=True)
            tk.Label(box,text=label,bg=PANEL,fg=MUTED,font=('Microsoft YaHei UI',9),anchor='w').pack(fill='x')
            value=tk.Label(box,text='0',bg=PANEL,fg=ACCENT if key=='drawn' else TEXT,font=('Consolas',21,'bold'),anchor='w')
            value.pack(fill='x');self.count_labels[key]=value
        self.figure=Figure(figsize=(12,8),dpi=100,facecolor=PANEL)
        self.cloud=CloudView(self.figure,self.range_m)
        self.canvas=FigureCanvasTkAgg(self.figure,master=scene)
        self.canvas.get_tk_widget().configure(bg=PANEL,highlightthickness=0)
        self.canvas.get_tk_widget().pack(fill='both',expand=True,padx=2,pady=2)
        self.canvas.mpl_connect('scroll_event',self._zoom_cloud)
        self.canvas.mpl_connect('draw_event',self._draw_finished)

        self.sidebar=tk.Frame(self.body,bg=PANEL,width=248,highlightbackground=EDGE,highlightthickness=1)
        self.sidebar.grid(row=0,column=1,sticky='nsew');self.sidebar.grid_propagate(False)
        self.sidebar.grid_rowconfigure(0,weight=1);self.sidebar.grid_columnconfigure(0,weight=1)
        scroll=tk.Canvas(self.sidebar,bg=PANEL,width=238,highlightthickness=0)
        bar=ttk.Scrollbar(self.sidebar,orient='vertical',command=scroll.yview)
        bar.grid(row=0,column=1,sticky='ns');scroll.grid(row=0,column=0,sticky='nsew')
        scroll.configure(yscrollcommand=bar.set)
        settings=tk.Frame(scroll,bg=PANEL);window=scroll.create_window((0,0),window=settings,anchor='nw')
        settings.bind('<Configure>',lambda e:scroll.configure(scrollregion=scroll.bbox('all')))
        scroll.bind('<Configure>',lambda e:scroll.itemconfigure(window,width=e.width))
        self._settings(settings)
        def bind_wheel(widget):
            widget.bind('<MouseWheel>',lambda e:scroll.yview_scroll(-int(e.delta/120),'units'),add='+')
            for child in widget.winfo_children():bind_wheel(child)
        bind_wheel(settings)

    def _settings(self,parent):
        def heading(text):
            tk.Label(parent,text=text,bg=PANEL,fg=TEXT,font=('Microsoft YaHei UI',10,'bold'),anchor='w').pack(fill='x',padx=12,pady=(16,8))
        def choice(label,values,initial,command):
            row=tk.Frame(parent,bg=PANEL);row.pack(fill='x',padx=12,pady=4)
            tk.Label(row,text=label,bg=PANEL,fg=MUTED,font=('Microsoft YaHei UI',9)).pack(side='left')
            box=ttk.Combobox(row,values=values,state='readonly',width=11);box.set(initial);box.pack(side='right')
            box.bind('<<ComboboxSelected>>',command);return box
        heading('数据与密度')
        self.source_box=choice('数据源',('360° 扇区','避障候选'),'避障候选',self._source_changed)
        self.history_box=choice('时间窗',('最新帧','2 秒','5 秒','10 秒'),'5 秒',self._history_changed)
        self.range_box=choice('视野',('自动全部','5','10','25','50','100'),'自动全部',self._range_changed)
        self.color_box=choice('颜色',('高度','距离'),'高度',self._display_options)
        self.size_box=choice('点大小',('细','标准','醒目'),'细',self._display_options)
        self.height_box=choice('高度比例',('1 倍','2 倍','4 倍'),'2 倍',self._display_options)
        self.layer_flags={};self.layer_widgets={}
        for name,label in [('ground','地面回波'),('pcla','障碍候选'),('wire','线状候选')]:
            flag=tk.BooleanVar(value=True);self.layer_flags[name]=flag
            box=tk.Checkbutton(parent,text=label,variable=flag,command=self._display_options,bg=PANEL,fg=TEXT,selectcolor='#263644',
                           activebackground=PANEL,activeforeground=TEXT,font=('Microsoft YaHei UI',9),anchor='w')
            box.pack(fill='x',padx=10);self.layer_widgets[name]=box
        heading('贴点轮廓')
        self.shape_box=choice('模式',('局部轮廓＋点云','仅点云','仅轮廓'),'局部轮廓＋点云',self._outline_options)
        self.group_box=choice('基础网格',('0.15 m','0.30 m','0.60 m'),'0.30 m',self._outline_options)
        tk.Label(parent,text='来自障碍与线状回波；空隙保留。点多时仅调整轮廓格距，不抽样原始点云。',bg=PANEL,fg=MUTED,font=('Microsoft YaHei UI',8),justify='left',anchor='w',wraplength=205).pack(fill='x',padx=12,pady=8)
        heading('数据核对')
        self.audit_label=tk.Label(parent,text='',bg=PANEL,fg=MUTED,font=('Microsoft YaHei UI',9),justify='left',anchor='nw',wraplength=210)
        self.audit_label.pack(fill='x',padx=12)
        self.metrics=tk.Label(parent,text='',bg=PANEL,fg=MUTED,font=('Microsoft YaHei UI',9),justify='left',anchor='w',wraplength=210)
        self.metrics.pack(fill='x',padx=12,pady=(12,8))
        tk.Label(parent,text='短时累积会保留运动残影。\n移动雷达时建议选“最新帧”。\n缓存 10 秒 / 最多 250,000 点。\n单帧有效点不按数量抽样。',bg=PANEL,fg='#d6b67c',font=('Microsoft YaHei UI',8),justify='left',anchor='w').pack(fill='x',padx=12,pady=(6,16))

    def _motor_bar(self,parent):
        row=tk.Frame(parent,bg=PANEL);row.pack(fill='x',padx=12,pady=8)
        tk.Label(row,text='实测',bg=PANEL,fg=MUTED,font=('Microsoft YaHei UI',9)).pack(side='left')
        self.rpm_value=tk.Label(row,text='0',bg=PANEL,fg=TEXT,font=('Consolas',22,'bold'),width=5);self.rpm_value.pack(side='left')
        tk.Label(row,text='RPM',bg=PANEL,fg=MUTED,font=('Consolas',9)).pack(side='left',padx=(0,20))
        self.target_value=tk.Label(row,text='900 RPM',bg=PANEL,fg=ACCENT,font=('Consolas',11,'bold'));self.target_value.pack(side='left',padx=6)
        self.rpm_var=tk.DoubleVar(value=900)
        self.rpm_scale=ttk.Scale(row,from_=0,to=1800,variable=self.rpm_var,command=self._rpm_changed,length=140)
        self.rpm_scale.pack(side='left',padx=8)
        self.apply_button=self._button(row,'应用转速',self.apply_speed);self.apply_button.pack(side='left',padx=5)
        self.start_button=self._button(row,'启动旋转',self.start_motor,True);self.start_button.pack(side='left',padx=5)
        self.stop_button=self._button(row,'停止',self.stop_motor);self.stop_button.configure(bg='#8c4449');self.stop_button.pack(side='left',padx=5)
        self.status_text=tk.Label(row,text='等待数据',bg=PANEL,fg=MUTED,font=('Microsoft YaHei UI',8),wraplength=250,justify='left');self.status_text.pack(side='right',padx=5)

    def _fullscreen(self,_event=None):self.root.attributes('-fullscreen',not self.root.attributes('-fullscreen'))

    def _toggle_sidebar(self):
        if self.sidebar.winfo_ismapped():self.sidebar.grid_remove()
        else:self.sidebar.grid()

    def _draw_finished(self,_event):
        if getattr(self,'_draw_started',None):self.draw_seconds=max(.08,time.monotonic()-self._draw_started)
        self._draw_started=None

    def _change_view(self,mode):
        if self.telemetry.cloud_source=='sectors' and mode!='俯视':
            self.footer_note.configure(text='扇区通道当前为方位—斜距图，高度尚未校准。三维视图请切换“避障候选”。')
            return
        self.cloud.set_mode(mode)
        for name,button in self.view_buttons.items():button.configure(bg='#21554f' if name==mode else '#1b2835')
        self.canvas.draw_idle()

    def _fit_cloud(self):
        self.cloud.fit_all();self.range_m=self.cloud.range_m;self.range_box.set('自动全部');self.canvas.draw_idle()

    def _zoom_cloud(self,event):
        if event.inaxes in (self.cloud.ax,self.cloud.map):
            self.cloud.set_range(self.cloud.range_m*(.85 if event.step>0 else 1/.85))
            self.range_m=self.cloud.range_m;self.range_box.set(f'{self.range_m:.1f}');self.canvas.draw_idle()

    def _range_changed(self,_event=None):
        if self.range_box.get()=='自动全部':self._fit_cloud()
        else:self.cloud.set_range(float(self.range_box.get()));self.canvas.draw_idle()

    def _set_plot_range(self,value):self.cloud.set_range(value);self.range_m=self.cloud.range_m;self.canvas.draw_idle()

    def _display_options(self,_event=None):
        self.cloud.layers={name:flag.get() for name,flag in self.layer_flags.items()}
        self.cloud.point_size={'细':3,'标准':8,'醒目':18}[self.size_box.get()]
        self.cloud.height_scale=float(self.height_box.get().split()[0]);self.cloud.apply_range()
        self.cloud.set_color('height' if self.color_box.get()=='高度' else 'distance');self.canvas.draw_idle()

    def _source_changed(self,_event=None):
        raw=self.source_box.get()=='360° 扇区'
        with self.telemetry.lock:self.telemetry.cloud_source='sectors' if raw else 'perception'
        self.frozen_snapshot=None;self.last_live_snapshot=None;self.freeze_button.configure(text='冻结观察')
        self.cloud.last=None;self.cloud.signature=None;self.cloud.auto_fit=True
        for flag in self.layer_flags.values():flag.set(True)
        self.cloud.layers=dict(ground=True,pcla=True,wire=True)
        for name,label in [('ground','地面回波'),('wire','线状候选'),('pcla','障碍候选')]:
            self.layer_widgets[name].configure(text='扇区回波' if raw and name=='pcla' else label,
                                               state='disabled' if raw and name!='pcla' else 'normal')
        self.color_box.set('距离' if raw else '高度')
        self.color_box.configure(state='disabled' if raw else 'readonly')
        self.height_box.configure(state='disabled' if raw else 'readonly')
        self.cloud.color_mode='distance' if raw else 'height'
        self._change_view('俯视' if raw else '3D')
        self.cloud.update(self.telemetry.snapshot(),force=True);self._fit_cloud()
        self.footer_note.configure(text='扇区图：方位按项目约定，零位待实物校准；半径为斜距，不是水平测距。空白不代表安全。' if raw else '左键旋转 · 中键平移 · 滚轮缩放 · 显示全部恢复完整视野')

    def _outline_options(self,_event=None):
        self.cloud.outline_mode=self.shape_box.get();self.cloud.group_radius=float(self.group_box.get().split()[0])
        self.cloud.update(self.frozen_snapshot or self.telemetry.snapshot(),force=True);self.canvas.draw_idle()

    def _history_changed(self,_event=None):
        with self.telemetry.lock:self.telemetry.history_seconds=0 if self.history_box.get()=='最新帧' else float(self.history_box.get().split()[0])
        self.cloud.signature=None

    def _clear_history(self):
        with self.telemetry.lock:
            self.telemetry.history.clear()
            self.telemetry.sector_history.clear()
            self.telemetry.sector_history.latest={name:[] for name in ('ground','wire','pcla')}
            self.telemetry.history.latest={name:[] for name in ('ground','wire','pcla')}
            self.telemetry.ground=[];self.telemetry.wire=[];self.telemetry.pcla=[]
        self.frozen_snapshot=None;self.freeze_button.configure(text='冻结观察');self.cloud.signature=None

    def _freeze_cloud(self):
        if self.frozen_snapshot:
            self.frozen_snapshot=None;self.freeze_button.configure(text='冻结观察')
        elif self.last_live_snapshot:
            self.frozen_snapshot=dict(self.last_live_snapshot,frozen=True);self.freeze_button.configure(text='恢复实时')
        self.cloud.signature=None

    def _export_cloud(self):
        snapshot=self.frozen_snapshot or self.last_live_snapshot
        if not snapshot:return
        destination=filedialog.asksaveasfilename(parent=self.root,title='导出当前数据窗的全部有效点（含关闭的图层）',defaultextension='.csv',
                                                initialfile='radar-'+time.strftime('%Y%m%d-%H%M%S')+'.csv',filetypes=[('CSV 点云','*.csv')])
        if not destination:return
        try:
            with open(destination,'w',newline='',encoding='utf-8-sig') as stream:
                writer=csv.writer(stream)
                if snapshot.get('cloud_source')=='sectors':
                    writer.writerow(['reference_bearing_deg_uncalibrated','slant_range_m','strength','record_slot','reference_x_projection_m','reference_y_projection_m'])
                    for x,y,_z,strength,index in snapshot['pcla']:
                        writer.writerow([math.degrees(math.atan2(y,x))%360,math.hypot(x,y),strength,index,x,y])
                else:
                    writer.writerow(['layer','x_m','y_m','z_m','metric','id'])
                    for layer in ('ground','wire','pcla'):
                        for point in snapshot[layer]:writer.writerow([layer,*point])
            self.footer_note.configure(text='已导出数据窗中的全部有效点：'+str(Path(destination)))
        except OSError as exc:messagebox.showerror('导出失败',str(exc),parent=self.root)

    def _refresh_cloud(self,snapshot):
        if snapshot.get('udp_age') is not None and snapshot['udp_age']<2.5:self.last_live_snapshot=snapshot
        shown=self.frozen_snapshot or snapshot
        if time.monotonic()-self._last_draw<max(.12,self.draw_seconds):return
        self._last_draw=time.monotonic()
        if self.cloud.update(shown) is not None:
            self._draw_started=time.monotonic();self.canvas.draw_idle()
        stats=self.cloud.last_stats
        values=dict(drawn=stats.get('plotted',0),available=stats.get('total',0),latest=stats.get('latest',0),
                    excluded=stats.get('outside',0)+stats.get('hidden',0)+stats.get('contour_only',0))
        for key,value in values.items():self.count_labels[key].configure(text=f'{value:,}')
        self.audit_label.configure(text=f"视野外：{stats.get('outside',0):,}\n关闭图层：{stats.get('hidden',0):,}\n仅轮廓隐藏：{stats.get('contour_only',0):,}\n无效坐标累计：{snapshot.get('invalid_points',0):,}\n容量淘汰累计：{snapshot.get('capacity_evicted',0):,}\n收到点数累计：{snapshot.get('received_points',0):,}\n实际格距：{stats.get('resolution',.3):.2f} m\n绘图约 {1/max(.1,self.draw_seconds):.1f} fps")
        self.view_hint.configure(text='冻结快照 / 接收仍继续' if self.frozen_snapshot else ('全量数据 / 自动范围' if self.cloud.auto_fit else '手动视野 / 可点显示全部'))
        if shown.get('cloud_source')=='sectors':
            bins=shown.get('sector_stats',{}).get('angular_bins',[0]*12)
            coverage=sum(n>0 for n in bins)
            self.view_hint.configure(text=f'扇区斜距图 · {coverage}/12 个方向区间有点'+(' · 冻结' if self.frozen_snapshot else ''))
