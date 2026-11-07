"""Responsive local settings. Network checks run only after the user presses a button."""
import json
import math
import os
import queue
import socket
import threading
import tkinter as tk
from tkinter import ttk
from urllib import request,error,parse
import paths
import state_store as store

LLM=paths.config('llm.json');UI=paths.config('ui.json')
LEVELS=(('off','关闭：只带窗口标题'),('light','轻量：最近2段'),('full','完整：最近5段'))
ENGINES=(('auto','自动选择'),('rapid','RapidOCR'),('windows','Windows 系统OCR'),('off','关闭OCR'))

def _read(path,default):
    try:
        with open(path,encoding='utf-8') as stream:value=json.load(stream)
        return value if isinstance(value,dict) else dict(default)
    except (OSError,ValueError):return dict(default)

def _write(path,data):
    os.makedirs(os.path.dirname(path),exist_ok=True)
    with store.state_lock(path):store._atomic_write(path,data)

def palette_from(skin):
    return {'bg':skin['bg'],'hi':skin['hi'],'text':skin['text'],'muted':skin['muted'],'faint':skin['muted'],
            'gold':skin['gold'],'green':skin['green'],'danger':'#ff8080','stroke':skin['hi'],'family':skin['family']}

def default_font(family,size,bold=False):return (family,size,'bold' if bold else 'normal')

class SettingsWindow:
    def __init__(self,master,palette,on_saved=None):
        self.master=master;self.pal=palette;self.on_saved=on_saved
        self.llm=_read(LLM,{'base_url':'http://127.0.0.1:8899/v1','api_key':'','model':'deepseek-v4.1-flash','interval_seconds':60})
        self.ui=_read(UI,{})
        self.vars={};self._inputs={};self._canvases=[];self._closed=False;self._busy=False;self._results=queue.Queue();self._models=[]
        self.top=tk.Toplevel(master);self.top.title('SideQuest 设置');self.top.configure(bg=palette['bg'])
        self.top.geometry('700x720');self.top.minsize(520,440)
        self.top.protocol('WM_DELETE_WINDOW',self.close);self.top.bind('<Escape>',lambda event:self.close())
        self._styles();self._build();self.top.bind('<MouseWheel>',self._wheel,add='+');self._poll=self.top.after(120,self._drain)

    def _styles(self):
        style=ttk.Style(self.top);style.theme_use('clam');p=self.pal
        style.configure('SQ.TNotebook',background=p['bg'],borderwidth=0)
        style.configure('SQ.TNotebook.Tab',background=p['hi'],foreground=p['muted'],padding=(14,9),font=(p['family'],10))
        style.map('SQ.TNotebook.Tab',background=[('selected',p['bg'])],foreground=[('selected',p['gold'])])
        style.configure('SQ.TCombobox',fieldbackground=p['hi'],background=p['hi'],foreground=p['text'],arrowcolor=p['muted'],bordercolor=p['stroke'],padding=5)
        style.map('SQ.TCombobox',fieldbackground=[('readonly',p['hi'])],foreground=[('readonly',p['text'])])
        for option,value in (('background',p['hi']),('foreground',p['text']),('selectBackground',p['gold']),('selectForeground',p['bg'])):
            self.top.option_add('*TCombobox*Listbox.'+option,value)
        style.configure('SQ.Vertical.TScrollbar',background=p['hi'],troughcolor=p['bg'],arrowcolor=p['muted'],borderwidth=0)

    def _label(self,parent,text,muted=False,bold=False):
        return tk.Label(parent,text=text,bg=self.pal['bg'],fg=self.pal['muted'] if muted else self.pal['text'],
                        font=(self.pal['family'],10,'bold' if bold else 'normal'),anchor='w',justify='left')

    def _button(self,parent,text,command,accent=False):
        return tk.Button(parent,text=text,command=command,font=(self.pal['family'],10),relief='flat',padx=14,pady=7,
                         bg=self.pal['gold'] if accent else self.pal['hi'],fg=self.pal['bg'] if accent else self.pal['text'],
                         activebackground=self.pal['hi'],activeforeground=self.pal['text'],cursor='hand2',takefocus=True)

    def _page(self,title):
        container=tk.Frame(self.book,bg=self.pal['bg']);self.book.add(container,text=title)
        canvas=tk.Canvas(container,bg=self.pal['bg'],highlightthickness=0)
        scroll=ttk.Scrollbar(container,orient='vertical',command=canvas.yview,style='SQ.Vertical.TScrollbar')
        canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        body=tk.Frame(canvas,bg=self.pal['bg']);item=canvas.create_window(0,0,window=body,anchor='nw')
        canvas.bind('<Configure>',lambda event:canvas.itemconfigure(item,width=event.width))
        body.bind('<Configure>',lambda event:canvas.configure(scrollregion=canvas.bbox('all')))
        self._canvases.append(canvas)
        return body

    def _field(self,parent,label,key,value,hint='',secret=False,combo=False):
        row=tk.Frame(parent,bg=self.pal['bg']);row.pack(fill='x',padx=20,pady=(12,4));row.columnconfigure(1,weight=1)
        self._label(row,label,muted=True).grid(row=0,column=0,sticky='nw',padx=(0,14),pady=7)
        row.columnconfigure(0,minsize=112)
        group=tk.Frame(row,bg=self.pal['bg']);group.grid(row=0,column=1,sticky='ew');group.columnconfigure(0,weight=1)
        variable=tk.StringVar(value=str(value if value is not None else ''));self.vars[key]=variable
        if combo:
            widget=ttk.Combobox(group,textvariable=variable,style='SQ.TCombobox',font=(self.pal['family'],10),state='normal')
        else:
            widget=tk.Entry(group,textvariable=variable,bg=self.pal['hi'],fg=self.pal['text'],insertbackground=self.pal['text'],
                            font=(self.pal['family'],10),relief='flat',highlightthickness=1,highlightbackground=self.pal['stroke'],highlightcolor=self.pal['gold'],show='•' if secret else '')
        widget.grid(row=0,column=0,sticky='ew',ipady=6);self._inputs[key]=widget
        if secret:
            shown=tk.BooleanVar(value=False)
            tk.Checkbutton(group,text='显示',variable=shown,command=lambda:widget.configure(show='' if shown.get() else '•'),
                           bg=self.pal['bg'],fg=self.pal['muted'],selectcolor=self.pal['hi'],activebackground=self.pal['bg'],font=(self.pal['family'],9)).grid(row=0,column=1,padx=(8,0))
        if hint:
            tip=self._label(row,hint,muted=True);tip.configure(font=(self.pal['family'],9));tip.grid(row=1,column=1,sticky='ew',pady=(6,0))
            tip.bind('<Configure>',lambda event:tip.configure(wraplength=max(140,event.width)))
        return widget

    def _check(self,parent,key,text,value):
        variable=tk.BooleanVar(value=bool(value));self.vars[key]=variable
        button=tk.Checkbutton(parent,text=text,variable=variable,bg=self.pal['bg'],fg=self.pal['text'],selectcolor=self.pal['hi'],
                              activebackground=self.pal['bg'],activeforeground=self.pal['text'],font=(self.pal['family'],10),anchor='w',justify='left')
        button.pack(fill='x',padx=20,pady=8)
        parent.bind('<Configure>',lambda event:button.configure(wraplength=max(200,event.width-70)),add='+')

    def _build(self):
        p=self.pal
        header=tk.Frame(self.top,bg=p['bg']);header.pack(fill='x',padx=20,pady=(18,12))
        self._label(header,'SideQuest 设置',bold=True).pack(anchor='w')
        caption=self._label(header,'配置模型连接、内容监测和日报；保存不会主动调用模型。',muted=True);caption.configure(font=(p['family'],9));caption.pack(fill='x',anchor='w',pady=(6,0))
        caption.bind('<Configure>',lambda event:caption.configure(wraplength=max(200,event.width)))
        footer=tk.Frame(self.top,bg=p['bg']);footer.pack(side='bottom',fill='x',padx=20,pady=14)
        self.status=self._label(footer,'',muted=True);self.status.pack(side='left',fill='x',expand=True);self.status.configure(wraplength=340,font=(p['family'],9))
        self._button(footer,'保存',self.save,True).pack(side='right',padx=(8,0));self._button(footer,'关闭',self.close).pack(side='right')
        footer.bind('<Configure>',lambda event:self.status.configure(wraplength=max(160,event.width-170)))
        self.book=ttk.Notebook(self.top,style='SQ.TNotebook');self.book.pack(fill='both',expand=True,padx=12)
        model=self._page('模型连接');monitor=self._page('监测与内容');display=self._page('界面与日报')
        self._field(model,'接口地址','base_url',self.llm.get('base_url',''),'填写 OpenAI 兼容的 /v1 地址，例如 http://127.0.0.1:8899/v1')
        self._field(model,'API Key','api_key',self.llm.get('api_key',''),'填写目标电脑接口要求的密钥。仅保存在本地，不写入连接检查日志。',secret=True)
        self._field(model,'模型名称','model',self.llm.get('model',''),'可以手动填写，也可以点击下方“获取模型”后从列表选择。',combo=True)
        buttons=tk.Frame(model,bg=p['bg']);buttons.pack(fill='x',padx=20,pady=(14,8))
        self.fetch_button=self._button(buttons,'获取模型',lambda:self._request_models('fetch'));self.fetch_button.pack(side='left')
        self.connect_button=self._button(buttons,'检测连通性',lambda:self._request_models('check'));self.connect_button.pack(side='left',padx=(10,0))
        self.connection=self._label(model,'仅请求 /models，不发聊天消息、不消耗模型生成 Token。',muted=True);self.connection.configure(font=(p['family'],9));self.connection.pack(fill='x',padx=20,pady=(4,15))
        model.bind('<Configure>',lambda event:self.connection.configure(wraplength=max(240,event.width-40)),add='+')
        self._field(model,'分析间隔（秒）','interval_seconds',self.llm.get('interval_seconds',60),'30–3600秒，默认60秒；这是AI分析频率，不影响2秒窗口停留计时。')
        self._check(monitor,'content_capture','读取窗口里显示的文字',self.llm.get('content_capture',True))
        self._check(monitor,'doc_read','允许读取 Excel / Word 的已保存原文作为辅助依据',self.llm.get('doc_read',True))
        self._label(monitor,'提供给模型的内容量',bold=True).pack(anchor='w',padx=20,pady=(18,8))
        level=tk.StringVar(value=self.llm.get('content_level','light'));self.vars['content_level']=level
        for key,text in LEVELS:
            tk.Radiobutton(monitor,text=text,value=key,variable=level,bg=p['bg'],fg=p['text'],selectcolor=p['hi'],activebackground=p['bg'],font=(p['family'],10)).pack(anchor='w',padx=24,pady=5)
        engine=self._field(monitor,'OCR 引擎','ocr_engine',self.llm.get('ocr_engine','auto'),'auto 自动选择；rapid 使用 RapidOCR；windows 使用系统OCR；off 关闭OCR。',combo=True)
        engine.configure(values=[key for key,_ in ENGINES],state='readonly')
        note=self._label(monitor,'修改监测方式后，请在主面板暂停再继续，让后台重新加载配置。',muted=True);note.configure(wraplength=450,font=(p['family'],9));note.pack(fill='x',padx=20,pady=16)
        note.bind('<Configure>',lambda event,label=note:label.configure(wraplength=max(200,event.width)))
        old_font=self.ui.get('font_size',10)
        self._initial_font=str(old_font if type(old_font) is int else 10)
        self._field(display,'面板字号','font_size',self._initial_font,'范围8–16。也可在主面板“外观与设置”中直接调整。')
        self._field(display,'日报生成时间','summary_hour',self.ui.get('summary_hour',18),'填写0–23的整点，默认18表示每天18:00。')
        note=self._label(display,'保存设置不会生成日报，也不会执行接口检测。',muted=True);note.configure(wraplength=450,font=(p['family'],9));note.pack(fill='x',padx=20,pady=16)

    def _wheel(self,event):
        try:
            if event.widget.winfo_toplevel()!=self.top:return
            index=self.book.index('current');canvas=self._canvases[index]
            first,last=canvas.yview()
            if last-first>=.999:return
            delta=event.delta
            if delta:canvas.yview_scroll((-1 if delta>0 else 1)*max(1,abs(round(delta/120))),'units')
        except (tk.TclError,IndexError):pass

    def _url(self):
        base=self.vars['base_url'].get().strip().rstrip('/');parts=parse.urlsplit(base)
        if parts.scheme not in ('http','https') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError('接口地址需为完整 http/https 地址，不能把密钥写在URL中。')
        return base

    def _request_models(self,mode):
        if self._busy:return
        try:base=self._url();key=self.vars['api_key'].get().strip()
        except ValueError as exc:self.connection.configure(text=str(exc),fg=self.pal['danger']);return
        self._busy=True;self.fetch_button.configure(state='disabled');self.connect_button.configure(state='disabled')
        self.connection.configure(text='正在'+('获取模型…' if mode=='fetch' else '检查接口连通性…'),fg=self.pal['muted'])
        def work():
            try:
                headers={'Accept':'application/json'}
                if key:headers['Authorization']='Bearer '+key
                with request.urlopen(request.Request(base+'/models',headers=headers),timeout=8) as response:
                    payload=response.read(2*1024*1024+1)
                    if len(payload)>2*1024*1024:raise ValueError('模型列表过大，请手动填写模型名。')
                data=json.loads(payload.decode('utf-8-sig'));records=data.get('data') if isinstance(data,dict) else None
                if not isinstance(records,list):raise ValueError('接口已响应，但模型列表格式不兼容；可手动填写模型名。')
                models=sorted({item.get('id').strip() for item in records if isinstance(item,dict) and isinstance(item.get('id'),str) and item.get('id').strip()},key=str.casefold)[:1000]
                self._results.put((mode,models,None))
            except error.HTTPError as exc:
                meaning={401:'密钥未通过认证',403:'当前密钥无模型列表权限',404:'接口未提供 /models；不能据此判定聊天接口不可用',429:'接口限流，请稍后再试'}.get(exc.code,'接口返回错误')
                self._results.put((mode,None,'HTTP '+str(exc.code)+'：'+meaning))
            except (socket.timeout,TimeoutError):self._results.put((mode,None,'连接超时，请确认目标电脑的本地服务已启动。'))
            except error.URLError as exc:self._results.put((mode,None,'连接失败：'+str(exc.reason)[:140]))
            except (ValueError,UnicodeError):self._results.put((mode,None,'接口响应不是兼容的模型列表；请核对 /v1 地址，或手动填写模型。'))
            except Exception as exc:self._results.put((mode,None,'检查未完成：'+type(exc).__name__))
        threading.Thread(target=work,daemon=True,name='SideQuest-model-list').start()

    def _drain(self):
        if self._closed:return
        try:
            while True:
                mode,models,problem=self._results.get_nowait();self._busy=False
                self.fetch_button.configure(state='normal');self.connect_button.configure(state='normal')
                if problem:self.connection.configure(text=problem,fg=self.pal['danger']);continue
                self._models=models;self._inputs['model'].configure(values=models)
                if mode=='fetch' and not self.vars['model'].get().strip() and models:self.vars['model'].set(models[0])
                text=('已获取 '+str(len(models))+' 个模型，可在模型名称处选择。' if mode=='fetch' else '连接成功，/models 已响应。未调用模型推理。')
                selected=self.vars['model'].get().strip()
                if selected and models and selected not in models:text+=' 当前填写的模型不在列表中，请确认名称。'
                self.connection.configure(text=text,fg=self.pal['green'])
        except queue.Empty:pass
        self._poll=self.top.after(120,self._drain)

    def _number(self,key,low,high):
        try:value=int(self.vars[key].get().strip())
        except (ValueError,tk.TclError):self._inputs[key].focus_set();raise ValueError('请为“'+{'interval_seconds':'分析间隔','font_size':'面板字号','summary_hour':'日报时间'}[key]+'”填写整数。')
        if not low<=value<=high:self._inputs[key].focus_set();raise ValueError('数值应在 '+str(low)+'–'+str(high)+' 范围内。')
        return value

    def _collect(self):
        llm=dict(self.llm);ui=dict(self.ui);llm['base_url']=self._url();llm['api_key']=self.vars['api_key'].get().strip();llm['model']=self.vars['model'].get().strip()
        if not llm['model']:self._inputs['model'].focus_set();raise ValueError('请填写或选择模型名称。')
        llm['interval_seconds']=self._number('interval_seconds',30,3600)
        for key in ('content_capture','doc_read'):llm[key]=bool(self.vars[key].get())
        llm['content_level']=self.vars['content_level'].get();llm['ocr_engine']=self.vars['ocr_engine'].get()
        font=self._number('font_size',8,16)
        if str(font)!=self._initial_font:ui['font_size']=font
        ui['summary_hour']=self._number('summary_hour',0,23)
        return llm,ui

    def save(self):
        try:llm,ui=self._collect()
        except ValueError as exc:self.status.configure(text=str(exc),fg=self.pal['danger']);return
        try:_write(LLM,llm);_write(UI,ui)
        except (OSError,TimeoutError) as exc:self.status.configure(text='保存未完成：'+str(exc)[:100],fg=self.pal['danger']);return
        self.llm,self.ui=llm,ui;self._initial_font=self.vars['font_size'].get().strip()
        self.status.configure(text='已保存。未自动执行网络检测。',fg=self.pal['green'])
        if self.on_saved:
            try:self.on_saved(llm,ui)
            except Exception:self.status.configure(text='已保存，应用到面板失败，请重新打开面板。',fg=self.pal['danger'])

    def close(self):
        if self._closed:return
        self._closed=True
        try:self.top.after_cancel(self._poll)
        except (tk.TclError,AttributeError):pass
        self.top.destroy()

    def focus(self):
        try:self.top.deiconify();self.top.lift();self.top.focus_force()
        except tk.TclError:pass
