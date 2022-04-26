#!/usr/bin/env python3

import tkinter as tk
from tkinter import messagebox as mb
import tkinter.font as tkFont
from tkinterhtml import HtmlFrame
from tkinter import ttk
import markdown
from PIL import Image,ImageTk,ImageDraw
from pdf2image import convert_from_path
from pathlib import Path
import os
import signal
import re
import time
import math
import subprocess
import configparser
from datetime import datetime, timedelta
from tempfile import TemporaryDirectory,NamedTemporaryFile

from abc import abstractmethod

from string import Template

import unicodedata

REC_TIMING_MARKER_END = 'END'
REC_TIMING_MARKER_SPECIAL = 'X'

DEFAULT_CONFIG_FILE = '~/.presenting_and_recording.config'


def make_dummy_image(width, height, marked=True):
  img = Image.new('RGB', (width,height), (0,0,0))
  if marked:
    draw = ImageDraw.Draw(img)
    draw.line((0,height, width, 0), fill=128, width=3)
  return ImageTk.PhotoImage(img)

class MediaProducer():
    
  def __init__(self, config, rec_basename, rec_basepath, pages, rec_timing_markers, 
                     rec_timing_file, get_record_animated_slides, get_record_screen_region, get_record_webcam, 
                     rec_audio_offset, rec_webcam_offset, rec_screencast_offset, rec_stdout = None):
    self.config = config
    self.rec_basename = rec_basename
    self.rec_basepath = rec_basepath
    self.pages = pages
    self.rec_timing_markers = rec_timing_markers
    self.rec_timing_file = rec_timing_file
    self.get_record_animated_slides = get_record_animated_slides
    self.get_record_screen_region = get_record_screen_region
    self.get_record_webcam = get_record_webcam
    self.rec_audio_offset = rec_audio_offset
    self.rec_webcam_offset = rec_webcam_offset
    self.rec_screencast_offset = rec_screencast_offset
    self.rec_stdout = rec_stdout
    self.rec_audio_compress = self.config.getboolean("RecordProduceCompressAudio", True)
    
  
  def join_video_audio(self, v, a, o, a_offset='00:00.00', v_offset='00:00.00', a_cut=False, v_cut=False, a_start='00:00.00', v_start='00:00.00'):
    cmd = ['ffmpeg','-y','-itsoffset',v_offset,'-ss',v_start]
    if v_cut is not False:
      cmd.extend(['-t',v_cut])
    cmd.extend(['-i',v,'-itsoffset',a_offset,'-ss',a_start])
    if a_cut is not False:
         cmd.extend(['-t',a_cut])
    cmd.extend(['-i',a,'-map','0:v','-map','1:a'])
    if not self.rec_audio_compress:
      cmd.extend(['-c','copy'])
    else:
      cmd.extend(['-c:v','copy','-c:a','aac'])
    cmd.append(o)
    if self.rec_stdout:
      print(' '.join(cmd), file=self.rec_stdout)
    else:
      print(' '.join(cmd))
    rec_joiner = subprocess.Popen(cmd, cwd=self.rec_basepath, stdout=subprocess.PIPE)
    rec_joiner.communicate()
    # ~ if a_start != '00:00.00' and v_start != '00:00.00':
      # ~ ext = Path(o).suffix
      # ~ rec_joiner = subprocess.Popen(['ffmpeg','-y','-i',o,'-start_at_zero','-map','0:v','-c:v','copy','-map','0:a','-c:a','copy','arg'+ext], cwd=self.rec_basepath, stdout=subprocess.PIPE)
      # ~ rec_joiner.communicate()
  
  def overlay_video(self, v1, v2, o, v2_offset='00:00.00'):
    w,h = self.get_width_and_height_from_video(v2)
    
    framerate = self.get_framerate_from_file(v2)
    framerate = str(framerate) if framerate else '25'
    
    frac = self.config.get("RecordProduceScreencastOverlayFractionWebcam", "6")
    xpos = self.config.get("RecordProduceScreencastOverlayPositionWebcamX", "10")
    ypos = self.config.get("RecordProduceScreencastOverlayPositionWebcamY", "10")
    
    filter_complex = f"[1:v][0:v]scale2ref=({w}/{h})*ih/{frac}/sar:ih/{frac}[wm][base];[base][wm]overlay={xpos}:{ypos}"
    cmd = ['ffmpeg', '-y', '-i', v1, '-itsoffset',v2_offset, '-i', v2, '-filter_complex', filter_complex, '-r', framerate, '-c:a', 'copy', o]
    if self.rec_stdout:
      print(' '.join(cmd), file=self.rec_stdout)
    else:
      print(' '.join(cmd))
    rec_joiner = subprocess.Popen(cmd, cwd=self.rec_basepath, stdout=subprocess.PIPE)
    rec_joiner.communicate()
  
  def get_framerate_from_file(self, filename):
    cmd = 'ffprobe -v error -select_streams v -of default=noprint_wrappers=1:nokey=1 -show_entries stream=r_frame_rate '+filename
    result = subprocess.run(cmd.split(' '), stdout=subprocess.PIPE)
    result = result.stdout.decode('utf-8').strip()
    if result:
      if '/' in result:
        for char in result:
          if char not in '0123456789+-*(). /':
            return None
        fps = eval(result, {"__builtins__":None}, {})
        return round(float(fps))
    else:
      return None
      
  def get_width_and_height_from_video(self, filename):
    cmd = 'ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 '+filename
    result = subprocess.run(cmd.split(' '), stdout=subprocess.PIPE)
    result = result.stdout.decode('utf-8').strip().split(',')
    return (result[0], result[1])
    
  def overlay_video_with_intro_maybe_outro(self, v1, v2, a, png, o, v2_offset='00:00.00'):
    w,h = self.get_width_and_height_from_video(v2)
    
    framerate = self.get_framerate_from_file(v2)
    framerate = str(framerate) if framerate else '25'

    intro_duration = self.config.get("RecordProduceScreencastOverlayIntroDuration", "3")
    outro_duration = self.config.get("RecordProduceScreencastOverlayOutroDuration", "3")
    frac = self.config.get("RecordProduceScreencastOverlayFractionWebcam", "6")
    xpos = self.config.get("RecordProduceScreencastOverlayPositionWebcamX", "10")
    ypos = self.config.get("RecordProduceScreencastOverlayPositionWebcamY", "10")
    
    cmd = ['ffmpeg', '-y', '-framerate', framerate,'-loop','1','-t',intro_duration,'-i', png, '-i', v1, '-itsoffset',v2_offset, '-i', v2, '-i',a,'-f','lavfi','-t','0.1','-i','anullsrc']
    if 'RecordProduceScreencastOverlayOutroImg' not in self.config:
      filter_complex = f"[2:v][1:v]scale2ref=({w}/{h})*ih/{frac}/sar:ih/{frac}[wm][base];[base][wm]overlay={xpos}:{ypos}[main];[0][4][main][3]concat=n=2:v=1:a=1[v][a]"
    else:
      outro = self.config.get("RecordProduceScreencastOverlayOutroImg")
      filter_complex = f"[2:v][1:v]scale2ref=({w}/{h})*ih/{frac}/sar:ih/{frac}[wm][base];[base][wm]overlay={xpos}:{ypos}[main];[0][4][main][3][5][4]concat=n=3:v=1:a=1[v][a]"
      cmd.extend(['-loop','1','-t',outro_duration,'-i', outro])
    cmd.extend(['-filter_complex', filter_complex, '-r', framerate, '-map', '[v]','-map', '[a]', o])
    if self.rec_stdout:
      print(' '.join(cmd), file=self.rec_stdout)
    else:
      print(' '.join(cmd))
    rec_joiner = subprocess.Popen(cmd, cwd=self.rec_basepath, stdout=subprocess.PIPE)
    rec_joiner.communicate()
  
  def ask_just_everything(self, rootwindow):
    just_everything = False
    
    if 'RecordProduceEverything' not in self.config:
      return mb.askyesnocancel(title="Produce Everything?",
                                     message="Click Yes if you want to produce all possible files, and\nNo if you want to be asked individually.\nCancel produces nothing",
                                     default=mb.YES)
    else:
      return self.config.getboolean("RecordProduceEverything")
  
  def produce_webcam(self, just_everything):
    if self.get_record_webcam:
      if just_everything or ( 'RecordProduceWebcamPlusAudio' not in self.config and mb.askyesno("Join video and audio?", "Do you want to join webcam video and audio?", default=mb.YES)) or self.config.getboolean('RecordProduceWebcamPlusAudio'):
        self.join_video_audio(self.rec_basename+'-webcam.mkv', self.rec_basename+'-audio.flac', self.rec_basename+'-webcam-audio.mkv', v_offset='-'+self.rec_webcam_offset, a_offset='-'+self.rec_audio_offset)
        if not just_everything:
          mb.showinfo("Done","Merging audio and video is done")
        return True
    return False
  
  def produce_screencast(self, rootwindow):
    just_everything = self.ask_just_everything(rootwindow)
    if just_everything is None:
      return
    
    if just_everything or ( 'RecordProduceScreencastPlusAudio' not in self.config and mb.askyesno("Join video and audio?", "Do you want to join screencast and audio now?", default=mb.YES)) or self.config.getboolean('RecordProduceScreencastPlusAudio'):
      self.join_video_audio(self.rec_basename+'-screencast.mkv', self.rec_basename+'-audio.flac', self.rec_basename+'-screencast-audio.mkv')
      if not just_everything:
        mb.showinfo("Done","Merging audio and video is done")
    
    self.produce_webcam(just_everything)
    if self.get_record_webcam:    
      if just_everything or ( 'RecordProduceScreencastOverlay' not in self.config and mb.askyesno("Overlay videos?", "Do you want to overlay the screencast and webcam video now?", default=mb.YES)) or self.config.getboolean('RecordProduceScreencastOverlay'):
        self.overlay_video(self.rec_basename+'-screencast.mkv', self.rec_basename+'-webcam-audio.mkv', self.rec_basename+'-screencast_overlayed.mp4', v2_offset='-'+self.rec_webcam_offset)
        if not just_everything:
          mb.showinfo("Done","Video overlay is done")
      
      if Path(self.rec_basename+'-title.png').exists() and (just_everything or ( 'RecordProduceScreencastOverlayWithTitle' not in self.config and mb.askyesno("Found a title-png!", "Do you want to produce overlayed screencast with intro now?", default=mb.YES)) or self.config.getboolean('RecordProduceScreencastOverlayWithTitle')):
        self.overlay_video_with_intro_maybe_outro(self.rec_basename+'-screencast.mkv', self.rec_basename+'-webcam.mkv', self.rec_basename+'-audio.flac', self.rec_basename+'-title.png', self.rec_basename+'-screencast_overlayed_title.mp4', v2_offset='-'+self.rec_webcam_offset)
        
        # ~ if not just_everything:
          # ~ mb.showinfo("Done","Video overlay with intro is done")
    
    mb.showinfo("Done", "All files produced")  
    
  def produce_recording(self, rootwindow):
    just_everything = self.ask_just_everything(rootwindow)
    if just_everything is None:
      return
    
    if not self.get_record_animated_slides:
      if just_everything or ( 'RecordProduceSlideshow' not in self.config and mb.askyesno("Recording finished", "Do you want to produce the slideshow file right away?", default=mb.YES)) or self.config.getboolean('RecordProduceSlideshow'):
        use_custom_geom = False
        p = None
        if 'RecordProduceCustomGeom' not in self.config:
        
          self.askGeom = inputGeomPopup(rootwindow)
          rootwindow.wait_window(self.askGeom.top)
        
          if self.askGeom.value:
            use_custom_geom = True
            p = self.askGeom.value.partition('x')
        else:
          use_custom_geom = True
          p = self.config.get('RecordProduceCustomGeom').partition('x')
          
        if use_custom_geom:
          custom_w = int(p[0])
          custom_h = int(p[2])
          print(f"{custom_w} X {custom_h}")
        
        if self.pages:
          with TemporaryDirectory() as tmpdir:
            i=0
            w=0
            h=0
            for i,page in enumerate(self.pages):
              fname = '{}/slide-{:03d}.png'.format(tmpdir,i)
              if use_custom_geom:
                h = custom_h
                w = custom_w
              else:
                h = min(rootwindow.winfo_screenheight(), 1080)
                w = int(round(h * page.width / page.height))
              img = page.resize((w,h), Image.ANTIALIAS)
              img.save(fname, 'png', compress_level=6)
            fname = '{}/slide-{:03d}.png'.format(tmpdir,i+1)
            img = ImageTk.getimage(make_dummy_image(w,h, marked=False))
            img.save(fname, 'png', compress_level=9)
            cmd = ["chap2ffconcat", self.rec_timing_file, '{}/slide-{{:03d}}.png'.format(tmpdir)]
            with NamedTemporaryFile() as tmpfile: 
              subprocess.run(cmd, stdout=tmpfile, cwd=self.rec_basepath)
              ts = str(math.floor(self.rec_timing_markers[-1].total_seconds()))
              cmd = ['ffmpeg','-y','-safe','0','-f','concat','-i',tmpfile.name,'-t',ts,'-c:v','libx264','-vf','format=yuv420p,fps=4','-fflags','+genpts','-movflags','+faststart',self.rec_basename+'-screen.mp4']
              # ~ cmd = ['ffmpeg','-y','-safe','0','-f','concat','-i',tmpfile.name,'-c:v','libx264','-vf','format=yuv420p','-fflags','+genpts','-movflags','+faststart',self.rec_basename+'-screen.mp4']
              rec_producer = subprocess.Popen(cmd, cwd=self.rec_basepath)
              rec_producer.communicate()
            

        if just_everything or ( 'RecordProduceSlidesPlusAudio' not in self.config and mb.askyesno("Join video and audio?", "Do you want to join slideshow and audio now?", default=mb.YES)) or self.config.getboolean('RecordProduceSlidesPlusAudio'):
          self.join_video_audio(self.rec_basename+'-screen.mp4', self.rec_basename+'-audio.flac', self.rec_basename+'-slides-audio.mkv', v_offset = self.rec_audio_offset)
          if not just_everything:
            mb.showinfo("Done","Merging audio and video is done")
      
    elif just_everything or ( 'RecordProduceSlidesPlusAudio' not in self.config and mb.askyesno("Join video and audio?", "Do you want to join slides-video and audio now?", default=mb.YES)) or self.config.getboolean('RecordProduceSlidesPlusAudio'):
      ts = str(math.floor(self.rec_timing_markers[-1].total_seconds()))
      self.join_video_audio(self.rec_basename+'-screen.mkv', self.rec_basename+'-audio.flac', self.rec_basename+'-screen-audio.mkv', v_cut=ts)
      if not just_everything:
        mb.showinfo("Done","Merging audio and video is done")
      
    self.produce_webcam(just_everything)
    
    geom = self.config.get("RecordTitleImageGeom", "960x540")
    geom = geom.partition('x')
    img = self.pages[0].resize((int(geom[0]), int(geom[2])), Image.ANTIALIAS)
    img.save(self.rec_basename+'-title.png', 'png', compress_level=1)
    
    mb.showinfo("Done", "All files produced")    

class DeltaTemplate(Template):
    delimiter = "%"

def strfdelta(tdelta, fmt):
  # based on https://stackoverflow.com/a/30536361
  d = {"D": tdelta.days}
  hours, rem = divmod(tdelta.seconds, 3600)
  minutes, seconds = divmod(rem, 60)
  d["H"] = '{:02d}'.format(hours)
  d["M"] = '{:02d}'.format(minutes)
  d["S"] = '{:02d}'.format(seconds)
  d["f"] = '{:03d}'.format(int(tdelta.microseconds / 1000))
  t = DeltaTemplate(fmt)
  return t.substitute(**d)

class chooseRegionPopup(object):
  def __init__(self,master,user_input=None):
      top=self.top=tk.Toplevel(master)
      self.fix_with_off=1
      self.fix_height_off=28
      self.geom = '1024x768+100+100'
      
      self.top.wait_visibility(self.top)
      self.top.attributes("-alpha", 0.5)
      
      b = tk.Button(self.top, text="GET POSITION", height=self.top.winfo_height(), width=self.top.winfo_width(), command=self.callback)
      b.grid(column=0,row=0,sticky='NSWE')
      
      if user_input:
        self.update_to_input(user_input)
      else:
        self.top.geometry(self.geom)
        self.top.update()
  
  def check(self, is_geom):
    m = re.match( r'^\d{2,4}x\d{2,4}\+\d{1,4}\+\d{1,4}', is_geom, re.M)
    if m:
      return True
    else: 
      return False
  
  def update_to_input(self,user_input):
    if self.check(user_input):
      parts = user_input.split('+')
      res = (parts[0]).split('x')
      # calculate offset induced by window decoration
      self.geom = "{}x{}+{}+{}".format(int(res[0])+self.fix_with_off,
                                    int(res[1])+self.fix_height_off,
                                    int(parts[1])-self.fix_with_off,
                                    int(parts[2])-self.fix_height_off)
        
      self.top.geometry(self.geom)
      self.top.update()
    else:
      if not mb.askyesno("No valid geometry", "No valid geometry entered. Do you want to choose one?"):
        self.no()
  
  def callback(self):
    pos=self.top.winfo_geometry()
    parts=pos.split('+')
    res = (parts[0]).split('x')
    
    self.geom = "{}x{}+{}+{}".format(int(res[0])-self.fix_with_off,
                               int(res[1])-self.fix_height_off,
                               self.top.winfo_x()+self.fix_with_off,
                               self.top.winfo_y()+self.fix_height_off)
    self.top.destroy()
                            
  def no(self):
    self.geom=None
    self.top.destroy()


class inputGeomPopup(object):
  def __init__(self,master):
      top=self.top=tk.Toplevel(master)
      self.l=tk.Label(top,text="Should the slides be produces with a certain geometry?")
      self.l.pack()
      self.e=tk.Entry(top)
      self.e.pack()
      self.b=tk.Button(top,text='Use this one',command=self.cleanup)
      self.b.pack()
      self.b=tk.Button(top,text='No',command=self.no)
      self.b.pack()
  
  def check(self, is_geom):
    m = re.match( r'^\d{2,4}x\d{2,4}', is_geom, re.M)
    if m:
      return True
    else: 
      return False
  
  def cleanup(self):
    val = self.e.get()
    if self.check(val):
      self.value=val
      self.top.destroy()
    else:
      if not mb.askyesno("No valid geometry", "Do you want to retry? No uses current window's dimension?"):
        self.no()
  
  def no(self):
    self.value=None
    self.top.destroy()


class BaseRecorder(tk.Frame):

  def __init__(self, parent, project_name, *args, **kwargs):
    self.is_initialized = False

    tk.Frame.__init__(self, parent, *args, **kwargs)

    self.root = parent
    self.root.wm_title("Presenter")   
    # ~ self.root.attributes('-fullscreen', True)
    # enable shortcuts
    self.root.bind('<KeyPress>', self.onKeyPress)
    self.root.protocol("WM_DELETE_WINDOW", self.close_window)
    
    self.rec_recorder = None
    self.rec_stdout = None
    self.rec_is_recording = False
    self.rec_is_paused = False
    self.rec_basepath = Path(os.getcwd()).absolute()
    self.rec_basename = self.slugify(project_name)
    self.rec_config_file = project_name + '.config'
    self.rec_notes_file = self.rec_basename + '.notes'
    self.rec_timing_file = project_name + '-timing.chap'
    self.rec_timing_chapters_file = project_name + '-chapters.chap'
    self.rec_timing_file_vtt = project_name + '.vtt'
    self.rec_timing_starttime = None
    self.rec_timing_markers = []
    self.pause_start = None
    self.pause_duration = timedelta()
    self.counter = 0
    self.max_count = 0
    
    self.init_config()
    
    self.md = markdown.Markdown(extensions=['nl2br','fenced_code'])
    self.notes_font_size = 2
    
    self.timer_format = "%H:%M:%S"
    
    max_w = round(self.root.winfo_screenwidth() * .95)
    max_h = round(self.root.winfo_screenheight() * .91)
    this_w = round(max_w * .35)
    
    self.clock_font = tkFont.Font(family="Lucida Grande", size=20)
    
    # ~ self.frame_left = tk.Frame(self.root, width=round(max_w * .75))
    # ~ self.frame_left.pack(fill=tk.BOTH, side=tk.LEFT, expand=1)
    
    self.slide_label = tk.Label(self.root, text="-/-", font=tkFont.Font(family="Lucida Grande", size=20))
    self.slide_label.grid(column=0, row=0, columnspan=2, sticky="NESW")
    
    # ~ self.cv2 = tk.Canvas(self.root, bd=1)#, relief=tk.RAISED)
    # ~ self.cv2.grid(column=0, row=1, columnspan=2, sticky="NESW", padx=5, pady=3)
    frame_up_group = tk.Frame(self.root)
    frame_up_group.grid(column=2, row=0, columnspan=2, rowspan=2, sticky="NESW", padx=20, pady=20)
    
    self.clock_label = tk.Label(frame_up_group, text=datetime.strftime(datetime.now(),self.timer_format), font=self.clock_font)
    self.clock_label.grid(column=0, row=0, columnspan=2, sticky="NESW")
    
    self.recording_timer_label = tk.Label(frame_up_group, text="00:00:00", font=self.clock_font)
    self.recording_timer_label.grid(column=0, row=1, columnspan=2, sticky="NESW")
    
    self.btn_text = tk.StringVar()
    btn = tk.Button(frame_up_group, textvariable = self.btn_text, command = self.toggle_recording)
    self.btn_text.set("Start Recording")
    btn.grid(column=0, row=2, rowspan=2, sticky="NESW")
    
    self.btn_rec_pause_text = tk.StringVar()
    btn_rec_pause = tk.Button(frame_up_group, textvariable = self.btn_rec_pause_text, command = self.toggle_recording_pause)
    self.btn_rec_pause_text.set("Pause Recording")
    btn_rec_pause.grid(column=1, row=2, rowspan=2, sticky="NESW")
    
    frame_ur = tk.Frame(frame_up_group)
    frame_ur.grid(column=2, row=0, rowspan=3, sticky="NESW")
    
    self.additional_source_webcam = tk.BooleanVar(value=False)
    self.additional_source_webcam_text = tk.StringVar()
    additional_source_webcam_check = tk.Checkbutton(frame_ur, textvariable=self.additional_source_webcam_text, variable=self.additional_source_webcam)
    self.additional_source_webcam_text.set("Webcam")
    additional_source_webcam_check.grid(column=0, row=0, columnspan=2, sticky="WN")
    
    self.additional_source_animated_slides = tk.BooleanVar(value=False)
    self.additional_source_animated_slides_check = tk.Checkbutton(frame_ur, text="Animated slides", variable=self.additional_source_animated_slides)
    self.additional_source_animated_slides_check.grid(column=0, row=1, columnspan=2, sticky="WN")
    
    self.additional_source_another_region = tk.BooleanVar(value=False)
    self.additional_source_another_region_check = tk.Checkbutton(frame_ur, text="Screencast region:", variable=self.additional_source_another_region)
    self.additional_source_another_region_check.grid(column=0, row=2, sticky="WN")
    
    self.second_offset_entry = tk.Entry(frame_ur)
    self.second_offset_entry.grid(column=1, row=2, sticky="NESW")
    
    self.btn_write_vtt = tk.BooleanVar(value=False)
    btn_write_vtt_check = tk.Checkbutton(frame_ur, text="Produce WebVTT file during recording", variable=self.btn_write_vtt)
    btn_write_vtt_check.grid(column=0, row=3, columnspan=2, sticky="WN")
    
    self.btn_keep_aspect_ratio = tk.BooleanVar(value=True)
    self.btn_keep_aspect_ratio_check = tk.Checkbutton(frame_ur, text="Keep Aspect Ratio while Resizing", variable=self.btn_keep_aspect_ratio)
    self.btn_keep_aspect_ratio_check.grid(column=0, row=4, sticky="WN", columnspan=2)
    
    
    frame_up_group.columnconfigure(0,weight=1)
    frame_up_group.columnconfigure(1,weight=1)
    frame_up_group.columnconfigure(2,weight=2)
    
    frame_up_group_bottom = tk.Frame(frame_up_group)
    frame_up_group_bottom.grid(column=0, row=4, columnspan=4, sticky="NESW")
    
    sep = ttk.Separator(frame_up_group_bottom, orient='horizontal')
    sep.grid(column=0, row=0, stick="NESW", pady=10, columnspan=2)
    # ~ info_label = tk.Label(frame_up_group_bottom, text="Additional Things:")
    # ~ info_label.grid(column=0, row=1, sticky="W")
    
    self.btn_fs = tk.Button(frame_up_group_bottom, text = "Toggle Slide Fullscreen", command = lambda: self.slide_window.attributes("-fullscreen",
                                                                                                    not self.slide_window.attributes("-fullscreen")))
    self.btn_fs.grid(column=0, row=1, sticky="W")
    
    btn_rect_text = tk.StringVar()
    btn_rect = tk.Button(frame_up_group_bottom, textvariable = btn_rect_text, command = self.choose_region)
    btn_rect_text.set("Choose Screen Region")
    btn_rect.grid(column=0, row=2, sticky="W")
    
    btn_wndw_text = tk.StringVar()
    btn_wndw = tk.Button(frame_up_group_bottom, textvariable = btn_wndw_text, command = self.choose_window)
    btn_wndw_text.set("Choose Window to Record")
    btn_wndw.grid(column=0, row=3, sticky="W")
    
    btn_rn_text = tk.StringVar()
    btn_rn = tk.Button(frame_up_group_bottom, textvariable = btn_rn_text, command = self.reload_notes)
    btn_rn_text.set("Reload Notes")
    btn_rn.grid(column=0, row=4, sticky="W")
    
    btn_rc_text = tk.StringVar()
    btn_rc = tk.Button(frame_up_group_bottom, textvariable = btn_rc_text, command = self.reload_config)
    btn_rc_text.set("Reload Config")
    btn_rc.grid(column=0, row=5, sticky="W")
    
    self.new_geometry_entry = tk.Entry(frame_up_group_bottom)
    self.new_geometry_entry.grid(column=1, row=2, sticky="WE")
    self.btn_rs_text = tk.StringVar()
    self.btn_rs = tk.Button(frame_up_group_bottom, textvariable = self.btn_rs_text, command = self.resize_to_input)
    self.btn_rs_text.set("Resize to Geometry")
    self.btn_rs.grid(column=1, row=1, sticky="W")
    
    self.notes_txt = HtmlFrame(self.root)
    # ~ self.notes_txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=1)
    self.notes_txt.grid(row=2,column=0,rowspan=2,columnspan=3, sticky="NESW")
    btn_font_plus  = tk.Button(self.root, text = "+", command = self.notes_fontsize_increase)
    btn_font_minus = tk.Button(self.root, text = "-", command = self.notes_fontsize_decrease)
    btn_font_plus.grid(row=2,column=3,sticky="NESW")
    btn_font_minus.grid(row=3,column=3,sticky="NESW")
    
    frame_up_group_bottom.columnconfigure(0,weight=1)
    frame_up_group_bottom.columnconfigure(1,weight=1)
    
    self.root.grid_columnconfigure(0, weight=3)
    self.root.grid_columnconfigure(1, weight=3)
    self.root.grid_columnconfigure(2, weight=3)
    self.root.grid_columnconfigure(3, weight=1, minsize=50)
    
    self.root.rowconfigure(0,weight=1, minsize=50)
    self.root.rowconfigure(1,weight=2)
    self.root.rowconfigure(2,weight=2)
    self.root.rowconfigure(3,weight=2)
    
    self.set_standard_values_to_gui()
    self.root.update()
    geom = "{}x{}+{}+{}".format(this_w, 
                                max_h,
                                60, 
                                30)
    self.root.geometry(geom)
    self.root.minsize(1000,596)
    self.root.update()
    self._after_id = None
    # ~ self.root.after(500, self.load_and_init, startslide, max_h)

  def choose_region(self):
    standard = f"1920x1080+{self.root.winfo_width()+150}+0"
    entered = self.second_offset_entry.get()
    self.askGeom = chooseRegionPopup(self.root, standard if entered == '' else entered)
    self.root.wait_window(self.askGeom.top)
  
    if self.askGeom.geom:
      geom = self.askGeom.geom
      parts = geom.split('+')
      res = (parts[0]).split('x')
      width = int(res[0])
      width = width-1 if width % 2 != 0 else width
      height = int(res[1])
      height = height-1 if height % 2 != 0 else height
      
      self.second_offset_entry.delete(0,tk.END)
      self.second_offset_entry.insert(0,f"{width}x{height}+{parts[1]}+{parts[2]}")
      self.additional_source_another_region.set(True)
      
  def choose_window(self):
    result = subprocess.check_output(['xwininfo'], universal_newlines=True)
    w=h=x=y=0
    for line in result.split('\n'):
      line = line.split(':',1)
      if 'Absolute upper-left X' in line[0]:
        x=line[1].strip()
      elif 'Absolute upper-left Y' in line[0]:
        y=line[1].strip()
      elif 'Width' in line[0]:
        w=line[1].strip()
      elif 'Height' in line[0]:
        h=line[1].strip()
    self.second_offset_entry.delete(0,tk.END)
    self.second_offset_entry.insert(0,f"{w}x{h}+{x}+{y}")
    self.additional_source_another_region.set(True)
  
  def init_config(self):
    config = configparser.ConfigParser()
    default_file = Path(DEFAULT_CONFIG_FILE).expanduser()
    if default_file.exists():
      config.read(default_file.resolve())
    specific_file = Path(self.rec_config_file).expanduser()
    if Path(specific_file).exists():
      print(f"read presentation-specific config from '{specific_file}'")
      config.read(specific_file.resolve())

    if config.defaults():
      self.config = config['DEFAULT']
    else:
      self.config = config['DEFAULT']
  
  def set_standard_values_to_gui(self):
    self.additional_source_animated_slides.set(self.config.getboolean('RecordAnimatedSlides', False))
    self.additional_source_webcam.set(self.config.getboolean('RecordWebcam', False))
    self.additional_source_another_region.set(self.config.getboolean('RecordRegion', False))
    self.btn_write_vtt.set(self.config.getboolean('RecordWriteWebVTT', False))
    self.btn_keep_aspect_ratio.set(self.config.getboolean('KeepAspectRatioWhileResizing', False))
    # ~ self.additional_source_webcam_text.set("Webcam".format(self.config.get("RecordWebcamDevice","/dev/video0")))
    
    if "RecordRegionGeom" in self.config:
      self.second_offset_entry.delete(0,tk.END)
      self.second_offset_entry.insert(0, self.config.get("RecordRegionGeom"))
    if "ResizeGeom" in self.config:
      self.new_geometry_entry.delete(0,tk.END)
      self.new_geometry_entry.insert(0, self.config.get("ResizeGeom"))
  
  def reload_config(self):
    self.init_config()
    self.set_standard_values_to_gui()
    self.reload_notes()
    self.update_counter_label()
  
  def get_keep_aspect_ratio(self):
    if self.is_initialized:
      return self.btn_keep_aspect_ratio.get()
    else:
      return False
  
  def get_record_animated_slides(self):
    if self.is_initialized:
      return self.additional_source_animated_slides.get()
    else:
      return False
  
  def get_record_webcam(self):
    if self.is_initialized:
      return self.additional_source_webcam.get()
    else:
      return False
  
  def get_record_second_region(self):
    if self.is_initialized:
      return self.additional_source_another_region.get()
    else:
      return False

  def get_valid_second_region(self):
    entered = self.second_offset_entry.get()
    if entered == '':
      return False
    else:
      m = re.match( r'^\d{2,4}x\d{2,4}\+\d{1,4}\+\d{1,4}', entered, re.M)
      if m:
        return True
      else: 
        return False

  def get_valid_geometry(self):
    entered = self.new_geometry_entry.get()
    if entered == '':
      return False
    else:
      m = re.match( r'^\d{2,4}x\d{2,4}', entered, re.M)
      if m:
        return True
      else: 
        return False
  
  def get_write_vtt(self):
    if self.is_initialized:
      return self.btn_write_vtt.get()
    else:
      return False
  
  def schedule_redraw(self, event):
    if self._after_id:
        self.after_cancel(self._after_id)
    if event.width != 30000 and event.height != 30000:
      self._after_id = self.after(2000, self.resize)
  
  def load_and_init(self):
    self.reload_notes()
    self.update_clock()
    self.update_counter_label()
    self.resize(initial=True)
    self.root.bind('<Configure>', self.schedule_redraw)
    self.is_initialized = True
  
  @abstractmethod
  def resize_to_input(self):
    pass
    
  @abstractmethod
  def resize(self, initial=False):
    pass

  def toggle_recording_pause(self):
    if self.rec_is_recording:
      if self.rec_is_paused:
        os.kill(self.rec_recorder.pid, signal.SIGCONT)
        self.rec_is_paused = False
        # ~ self.log_timing('REC_RESUME')
        self.btn_rec_pause_text.set("Pause Recording")
        self.pause_duration += datetime.now() - self.pause_start
        self.pause_start = None
        print(self.pause_duration)
      else:
        os.kill(self.rec_recorder.pid, signal.SIGSTOP)
        # ~ self.log_timing('REC_PAUSE')
        self.rec_is_paused = True
        self.btn_rec_pause_text.set("Resume Recording")
        self.pause_start = datetime.now()
        
  def ffmpeg_configure_and_start(self):
    
    if "FfmpegSourceAudio" not in self.config:
        mb.showinfo("Whoops!", "You need to specify 'FfmpegSourceAudio' in your config file")
        return False
    
    def validate_screen_config():
      if "FfmpegSourceScreen" not in self.config or "FfmpegOutputScreen" not in self.config:
        mb.showinfo("Whoops!", "You need to specify 'FfmpegSourceScreen' and 'FfmpegOutputScreen' in your config file")
        return False
      source = self.config.get("FfmpegSourceScreen")
      if not all(specifier in source for specifier in ['@WIDTH@','@HEIGHT@','@X@','@Y@']):
        mb.showinfo("Whoops!", "'FfmpegSourceScreen' must contain '@WIDTH@','@HEIGHT@','@X@','@Y@' at some point")
        return False
    
    audioFile  = self.rec_basename+'-audio.flac'
    screenFile = self.rec_basename+'-screen.mkv'
    screencastFile = self.rec_basename+'-screencast.mkv'
    webcamFile = self.rec_basename+'-webcam.mkv'
    recordLogFile = self.rec_basename+'-ffmpeg.log'
    
    cmd = f"ffmpeg -y -nostdin"
    out_map = ""
    i_n = 0
    
    if self.get_record_webcam():
      if "FfmpegSourceWebcam" not in self.config or "FfmpegOutputWebcam" not in self.config:
        mb.showinfo("Whoops!", "You need to specify 'FfmpegSourceWebcam' and 'FfmpegOutputWebcam' in your config file")
        return False
      cmd += ' '+self.config.get("FfmpegSourceWebcam")
      out_map += ' '+f"-map {i_n}:v:0 "+ self.config.get("FfmpegOutputWebcam") + ' ' + webcamFile
      i_n += 1
    
    if self.get_record_second_region() and self.get_valid_second_region():
      validate_screen_config()
      geom = self.second_offset_entry.get()
      parts = geom.split('+')
      res = (parts[0]).split('x')
      width = int(res[0])
      width = width-1 if width % 2 != 0 else width
      height = int(res[1])
      height = height-1 if height % 2 != 0 else height
      source = self.config.get("FfmpegSourceScreen").replace('@WIDTH@', str(width)).replace('@HEIGHT@',str(height)).replace('@X@', parts[1]).replace('@Y@', parts[2])
      cmd += ' '+source
      out_map += ' '+f"-map {i_n}:v:0 "+ self.config.get("FfmpegOutputScreen") + ' ' + screencastFile
      i_n += 1
      
    if self.get_record_animated_slides():
      validate_screen_config()
      geom = self.slide_viewer.get_recording_geom()
      if geom[0] % 2 != 0:
        geom = (geom[0]-1, geom[1], geom[2]+1, geom[3])
      if geom[1] % 2 != 0:
        geom = (geom[0], geom[1]-1, geom[2], geom[3]+1)
      source = self.config.get("FfmpegSourceScreen").replace('@WIDTH@', str(geom[0])).replace('@HEIGHT@',str(geom[1])).replace('@X@', str(geom[2])).replace('@Y@', str(geom[3]))
      
      cmd += ' '+source
      out_map += ' '+f"-map {i_n}:v:0 "+ self.config.get("FfmpegOutputScreen") + ' ' + screenFile
      i_n += 1
      
    cmd += ' '+self.config.get("FfmpegSourceAudio")
    if 'FfmpegOutputAudio' in self.config:
      out_map += ' '+f"-map {i_n}:a:0 "+ self.config.get("FfmpegOutputAudio") + ' ' + audioFile
    else:
      out_map += ' '+f"-map {i_n}:a:0 {audioFile}"
    
    cmd = cmd + out_map
    self.rec_stdout = open(recordLogFile, 'w')
    print(cmd)
    print(cmd, file=self.rec_stdout)
    
    success = False
    self.rec_recorder = subprocess.Popen(cmd.split(' '), stdout=self.rec_stdout, stderr=self.rec_stdout, universal_newlines=True)
    with open(recordLogFile, 'r') as log:
      go_on = True
      self.rec_audio_start = self.rec_webcam_start = self.rec_screencast_start = datetime.now()
      
      audio_match = re.compile(r'^Output [^\']*\''+audioFile+'\'', re.M)
      webcam_match = re.compile(r'^Output [^\']*\''+webcamFile+'\'', re.M)
      screencast_match = re.compile(r'^Output [^\']*\''+screencastFile+'\'', re.M)
      start_match = re.compile(r'^(frame|size)= *\d+', re.M)
      error_match = re.compile(r'^.*(Device or resource busy|Inappropriate ioctl for device|Input/output error|not found)$', re.M)
      while go_on:
        for line in log:
          # ~ print(line.strip())
          m = audio_match.match(line)
          if m:
            self.rec_audio_start = datetime.now()
          m = webcam_match.match(line)
          if m:
            self.rec_webcam_start = datetime.now()
          m = screencast_match.match(line)
          if m:
            self.rec_screencast_start = datetime.now()
          m = start_match.match(line)
          if m:
            self.rec_timing_starttime = datetime.now()
            go_on = False
            success = True
            break
          m = error_match.match(line)
          if m:
            go_on = False
            success = False
            break
    if not success:
      mb.showinfo("Whoops!", "Something's wrong with your recording-device specifications. Try to reload config")
    else:
      diff = self.rec_timing_starttime - self.rec_audio_start
      diff = strfdelta(diff, "%H:%M:%S.%f")
      print(f"audiooffset={diff}", file=self.rec_stdout)
      
      if self.get_record_webcam():
        diff = self.rec_timing_starttime - self.rec_webcam_start
        diff = strfdelta(diff, "%H:%M:%S.%f")
        print(f"webcamoffset={diff}", file=self.rec_stdout)
      
      if self.get_record_second_region() or self.get_record_animated_slides():
        diff = self.rec_timing_starttime - self.rec_screencast_start
        diff = strfdelta(diff, "%H:%M:%S.%f")
        print(f"screencastoffset={diff}", file=self.rec_stdout)
    return success
  
  @abstractmethod
  def call_producer(self, audio_offset, webcam_offset, screencast_offset):
    pass
  
  def toggle_recording(self):
    if self.rec_is_recording:
      self.btn_text.set("Start Recording")
      self.log_timing(marker=REC_TIMING_MARKER_END)
      self.rec_is_recording = False
      if self.rec_recorder:
        if self.get_record_webcam():
          time.sleep(1)
        if self.get_record_animated_slides():
          time.sleep(3)
        self.rec_recorder.send_signal(signal.SIGINT)
        self.rec_recorder.wait()
      
      audio_offset = strfdelta(self.rec_timing_starttime - self.rec_audio_start, "%H:%M:%S.%f")
      webcam_offset = strfdelta(self.rec_timing_starttime - self.rec_webcam_start, "%H:%M:%S.%f")
      screencast_offset = strfdelta(self.rec_timing_starttime - self.rec_screencast_start, "%H:%M:%S.%f")
      self.call_producer(audio_offset, webcam_offset, screencast_offset)                               
      
      self.rec_timing_starttime = None
      if self.rec_stdout:
        self.rec_stdout.close()
    else:
      if self.get_record_second_region() and not self.get_valid_second_region():
        mb.showinfo("No valid geometry", "Please enter a valid region of the screen if you want to record a screen cast!")
      else:
        if self.ffmpeg_configure_and_start():
          self.btn_text.set("Stop Recording")
          self.rec_is_recording = True
          self.log_timing(start=True)
  
  def get_title_to_log(self, counter):
    cur_title = "{:02d}".format(counter)
    if cur_title in self.titles:
      return self.titles[cur_title]
    else:
      return None
    
  
  def log_timing(self, marker=None, start=False):
    out_mark = self.counter + 1 if marker is None else marker
    
    if start:
      with open(self.rec_timing_file, 'w') as tf:
        print("{} S".format(self.rec_timing_starttime), file=tf)
      if self.titles:
        with open(self.rec_timing_chapters_file, 'w') as tf:
          print("{} S".format(self.rec_timing_starttime), file=tf)
      if self.get_write_vtt():
        with open(self.rec_timing_file_vtt, 'w') as tf:
          print("WEBVTT\n\n", end='', file=tf)
    
    if self.rec_is_recording and not self.rec_is_paused:
      diff = datetime.now() - self.rec_timing_starttime - self.pause_duration
      self.rec_timing_markers.append(diff)
      with open(self.rec_timing_file, 'a') as tf:
        print("{} {}".format(strfdelta(diff, "%H:%M:%S.%f"), out_mark), file=tf)
      if self.titles and marker is None:
        title = self.get_title_to_log(self.counter+1)
        with open(self.rec_timing_chapters_file, 'a') as tf:
          print("{} {}".format(strfdelta(diff, "%H:%M:%S.%f"), title), file=tf)
      if self.get_write_vtt():
        with open(self.rec_timing_file_vtt, 'a') as tf:
          diff = strfdelta(diff, "%H:%M:%S,%f")
          last_title = self.get_title_to_log(self.counter)
          if not start:
            print("{}\n- {}\n".format(diff, last_title), end='', file=tf)
          else:
            diff = "00:00:00,000"
          if marker != REC_TIMING_MARKER_END:
            print("\n{}\n{} --> ".format(out_mark, diff), end='', file=tf)
    
  
  def next_block(self):
    if self.counter < self.max_count:
      self.counter += 1
      self.update_notes()
      self.log_timing()
      self.update_counter_label()
      self.next_block_special()
  
  @abstractmethod
  def next_block_special(self):
    pass

  @abstractmethod
  def previous_block_special(self):
    pass

  def previous_block(self):
    if self.counter > 0:
      self.counter -= 1
      self.update_notes()
      self.log_timing()
      self.update_counter_label()
      self.previous_block_special()
  
  def update_counter_label(self):
    self.slide_label.configure(text=f"{self.counter+1}/{self.max_count}")
  
  def notes_fontsize_increase(self):
    self.notes_font_size += 2
    self.update_notes()
    
  def notes_fontsize_decrease(self):
    self.notes_font_size -= 2
    self.update_notes()
  
  def update_max_count(self):
    self.max_count = len(self.notes)
  
  def reload_notes(self):
    self.notes, self.titles = self.load_notes_and_titles()
    self.update_max_count()
    self.update_notes()
  
  def update_notes(self):
    self.notes_txt.set_content('<html></html>')
    i = "{:02d}".format(self.counter+1)
    title = ''
    if self.config.getboolean("NotesShowTitle", False) and i in self.titles:
      title = '<h2>{}</h2>'.format(self.titles[i])
    if i in self.notes:
      self.notes_txt.set_content('<html>{}<font size="+{}">{}</font></html>'.format(title,self.notes_font_size,self.notes[i]))

  def onKeyPress(self, event):
    kc = event.keycode
    ch = event.char
    if kc == 114 or kc == 116 or ch == 'n':
      self.next_block()
    elif kc == 111 or kc == 113 or ch == 'p':
      self.previous_block()
    elif ch == '+':
      self.notes_fontsize_increase()
    elif ch == '-':
      self.notes_fontsize_decrease()
    elif ch == 'r':
      self.toggle_recording()
    elif ch == 'x':
      self.log_timing(REC_TIMING_MARKER_SPECIAL)

  def update_preview_img(self):
    imprev = self.list_preview_images[self.counter + 1]
    if self.counter > 0:
      self.cv2.delete("all")
    self.cv2.create_image(self.cv2.winfo_width()/2, self.cv2.winfo_height()/2, anchor = tk.CENTER, image = imprev)

  def update_clock(self):
    now = datetime.now()
    col = '#FF0000' if self.rec_is_recording else '#000000'
    self.clock_label.configure(text=datetime.strftime(now,self.timer_format))
    self.recording_timer_label.configure(fg=col)
    if self.rec_is_recording and not self.rec_is_paused:
      diff = now - self.rec_timing_starttime - self.pause_duration
      diff = str(diff).split('.')[0]
      self.recording_timer_label.configure(text = datetime.strftime(datetime.strptime(diff, "%H:%M:%S"), self.timer_format), fg=col)
    self.root.after(1000, self.update_clock)

  def load_notes_and_titles(self):
    notes = {}
    titles = {}
    p = Path(self.rec_notes_file)
    pptx = Path(self.config.get("PathToPPTX",self.rec_notes_file.replace('.notes', '.pptx')))
    if not p.exists():
      if pptx.exists():
        print("loading slide infos from",pptx.resolve())
        cmd = ["extractnotes", pptx.resolve(), p.resolve()]
        subprocess.run(cmd, cwd=self.rec_basepath)
      else:
        print(f"could not find notes at expected location '{str(p)}'")
    
    if p.exists():
      cur = []
      cur_s = None
      with open(p,'r') as _f:
        for line in _f:
          m = re.match( r'^#\s*(\d+)', line, re.M)
          if m:
            if cur_s in notes:
              raise Exception('slide has more than one notes section')
            if cur_s is not None:
              notes[cur_s] = self.md.convert((''.join(cur)).strip())
            cur = []
            cur_s = (m.group(0)).replace('#','').strip()
          else:
            m = re.match( r'^#title:\s+(.*)', line, re.M)
            if m:
              if cur_s is not None:
                titles[cur_s] = m.group(1).strip()
            else:
              cur.append(line)
        # ~ notes[cur_s] = cur
        notes[cur_s] = self.md.convert((''.join(cur)).strip())
    return notes, titles
      
  def close_window(self):
    if self.rec_is_recording:
      self.rec_recorder.terminate()
    self.root.destroy()
  
  
  def slugify(self, value, allow_unicode=False):
    """
    Taken from https://github.com/django/django/blob/master/django/utils/text.py
    Convert to ASCII if 'allow_unicode' is False. Convert spaces or repeated
    dashes to single dashes. Remove characters that aren't alphanumerics,
    underscores, or hyphens. Convert to lowercase. Also strip leading and
    trailing whitespace, dashes, and underscores.
    """
    # adapted so it keeps dots inside filenames
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize('NFKC', value)
    else:
        value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w.\s-]', '', value.lower())
    return re.sub(r'[-\s]+', '-', value).strip('-_')


class SlideView:
  def __init__(self, parent, controller):
    self.parent = parent
    self.controller = controller
    self.resize_from_update = False
    self.parent.bind('<KeyPress>', self.controller.onKeyPress)
    self.max_w = round(self.parent.winfo_screenwidth() * .97)
    self.max_h = round(self.parent.winfo_screenheight() * .94)
    self.frame = tk.Frame(self.parent, width=round(self.max_w * .75), height=self.max_h, bg="black")
    # ~ self.max_w = 1920
    # ~ self.max_h = 1080
    # ~ self.frame = tk.Frame(self.parent, width=self.max_w+6, height=self.max_h+6, bg="black")
    self.frame.pack(fill=tk.BOTH, expand=1)
    self.defaultbg = self.parent.cget('bg')

    self.cv1 = tk.Canvas(self.frame, highlightthickness=0)#, relief=tk.RAISED)
    self.cv1.pack(fill=tk.BOTH, expand=1)
    # ~ self.quitButton = tk.Button(self.frame, text = 'Quit', width = 25, command = self.close_windows)
    # ~ self.quitButton.pack()
    self.parent.bind('<Configure>', self.schedule_redraw)
    self.parent.protocol("WM_DELETE_WINDOW", self.close_window)
    self._after_id = None
    self.parent.update()
    self.parent.bind("<F11>", lambda event: self.parent.attributes("-fullscreen",
                                        not self.parent.attributes("-fullscreen")))
    self.parent.bind("<Escape>", lambda event: self.parent.attributes("-fullscreen", False))
    self.last_geom = "{}x{}".format(self.parent.winfo_width(), self.parent.winfo_height())
    # ~ self.last_geom = "1920x1080"
  
  def schedule_redraw(self, event):
    # ~ print(self.resize_from_update, event)
    if self._after_id:
      # ~ print(self._after_id)
      self.parent.after_cancel(self._after_id)
    if not self.resize_from_update:
      use_aspect_ratio = self.controller.get_keep_aspect_ratio()
      if use_aspect_ratio:
        new_h = round(int(event.width) / self.aspect_ratio)
        if new_h > self.max_h:
          new_h = self.max_h # if given height exceeds max, use max
        new_w = round(new_h * self.aspect_ratio) # derive width
        if new_w > self.max_w: # if it exceeds max width
          new_w = self.max_w # use max
          new_h = round(new_w / self.aspect_ratio) # and downsize height
        geom = "{}x{}".format(new_w, new_h)
      else:
        geom = "{}x{}".format(event.width, event.height)
      self._after_id = self.parent.after(2000, self.resize, False, geom, use_aspect_ratio)
      
      
  def init(self, pages, startslide):
    self.pages = pages
    self.startslide = int(startslide)
    self.current_slide = self.startslide
    self.resize(initial=True, geom=None)
    self.aspect_ratio = self.list_images[0].width() / self.list_images[0].height()
  
  def resize(self, initial=False, geom=None, resize_frame=False):
    if geom is None or geom != self.last_geom:
      if geom is not None:
        self.last_geom = geom
      if resize_frame:
        parted = geom.partition('x')
        new_w = int(parted[0])
        new_h = int(parted[2])
        if not self.resize_from_update:
          self.resize_from_update = True
          self.parent.geometry(geom)
      else:
        new_w = self.frame.winfo_width()
        new_h = self.frame.winfo_height()
      pic_width = new_w
      pic_height = new_h
      self.list_images = []
      # Storing the converted images into list
      max_w = 0
      for i in range(len(self.pages)):
        img = self.pages[i].copy()
        img.thumbnail((pic_width,pic_height), Image.ANTIALIAS)
        max_w = max(max_w, img.size[0])
        self.list_images.append(ImageTk.PhotoImage(img))
      self.list_images.append(make_dummy_image(self.list_images[0].width(),self.list_images[0].height(), marked=False))
      self.cv1.config(width = self.list_images[0].width(), height=self.list_images[0].height())
      if self.parent.attributes("-fullscreen"):
        self.cv1.config(background="black")
      else:
        self.cv1.config(background=self.defaultbg)
      self.update_main_img()
  
  def update_main_img(self):
    im = self.list_images[self.controller.counter]
    # ~ self.cv1.delete("all")
    self.parent.update()
    self.cv1.create_image(self.cv1.winfo_width()/2, self.cv1.winfo_height()/2, anchor = tk.CENTER, image = im)
  
  def close_window(self):
    self.controller.close_window()
    
  def get_recording_geom(self):
    self.parent.update()
    im = self.list_images[self.controller.counter]
    x0 = self.frame.winfo_rootx() + round(self.cv1.winfo_width()/2) - round(im.width()/2)
    y0 = self.frame.winfo_rooty() + round(self.cv1.winfo_height()/2) - round(im.height()/2)
    return (im.width(),im.height(),x0,y0)


class PresenterView(BaseRecorder):

  def __init__(self, parent, pdffile, startslide, *args, **kwargs):
    super().__init__(parent, pdffile.replace('.pdf',''))
    self.is_initialized = False
    
    self.pdffile = pdffile if pdffile.endswith('.pdf') else pdffile+'.pdf'

    max_w = round(self.root.winfo_screenwidth() * .95)
    max_h = round(self.root.winfo_screenheight() * .91)
    this_w = round(max_w * .35)
    slide_w = round(max_w * .55)
    slide_h = max_h
    # ~ slide_w = 1926
    if 'SlideGeom' in self.config:
      g = self.config.get('SlideGeom')
      g = g.partition('x')
      slide_w = int(g[0])
      slide_h = int(g[2])
    
    # todo initialize screen size correctly!
    self.slide_window = tk.Toplevel(self.root)
    self.slide_window.geometry("{}x{}+{}+{}".format(slide_w, #slide_w
                                slide_h,
                                30, 
                                30))
    self.slide_viewer = SlideView(self.slide_window, self)
    self.root.bind("<F11>", lambda event: self.slide_window.attributes("-fullscreen",
                                        not self.slide_window.attributes("-fullscreen")))
    self.root.bind("<Escape>", lambda event: self.slide_window.attributes("-fullscreen", False))
    
    self.cv2 = tk.Canvas(self.root, bd=1)#, relief=tk.RAISED)
    self.cv2.grid(column=0, row=1, columnspan=2, sticky="NESW", padx=5, pady=3)
    
    self.root.grid_columnconfigure(0, weight=3)
    self.root.grid_columnconfigure(1, weight=3)
    self.root.grid_columnconfigure(2, weight=3)
    self.root.grid_columnconfigure(3, weight=1, minsize=50)
    
    self.root.rowconfigure(0,weight=1, minsize=50)
    self.root.rowconfigure(1,weight=2)
    self.root.rowconfigure(2,weight=2)
    self.root.rowconfigure(3,weight=2)
    
    self.root.update()
    geom = "{}x{}+{}+{}".format(this_w, 
                                max_h,
                                slide_w+60, 
                                30)
    self.root.geometry(geom)
    self.root.minsize(1000,596)
    self.root.update()
    self._after_id = None
    self.root.after(500, self.load_and_init, startslide, max_h)
  
  def load_and_init(self, startslide, max_h):
    # Here the PDF is converted to list of images
    dpi = self.config.getint('SlideLoadDpi', 300)
    hfac = self.config.getfloat('SlideLoadHeightFactor', 2.0)
    self.pages = convert_from_path(self.pdffile,size=(None, max_h*hfac),dpi=dpi)
    self.slide_viewer.init(self.pages, self.counter)
    super().load_and_init()
    self.counter = int(startslide)-1
    self.max_count = len(self.pages)
    self.update_counter_label()
  
  def update_max_count(self):
    self.max_count = len(self.pages)
    
  def resize_to_input(self):
    if self.get_valid_geometry():
      other_geom = self.new_geometry_entry.get() # 1178x730+154+327
      self.slide_viewer.resize(geom=other_geom, resize_frame=True)
    
  def resize(self, initial=False):
    # call self
    if initial:
      self.list_preview_images = []
      prev_pic_width = self.cv2.winfo_width()
      prev_pic_height = self.cv2.winfo_height()
      # Create Preview images
      for i in range(len(self.pages)):
        img = self.pages[i].copy()
        img.thumbnail((prev_pic_width,prev_pic_height), Image.ANTIALIAS)
        self.list_preview_images.append(ImageTk.PhotoImage(img))
      # append a black screen at the end
      self.list_preview_images.append(make_dummy_image(self.list_preview_images[0].width(),self.list_preview_images[0].height(), marked=False))
      self.list_preview_images.append(make_dummy_image(self.list_preview_images[0].width(),self.list_preview_images[0].height()))
    if len(self.pages) >= 2:
      self.update_preview_img()
    
    # ~ if not initial:
      # ~ self.frame_left.config(width=max_w)
      # ~ self.frame_right.config(width=self.root.winfo_width()-max_w)
      # ~ self.notes_txt.config(width=self.root.winfo_width()-max_w-30)

  def call_producer(self, audio_offset, webcam_offset, screencast_offset):
    Producer = MediaProducer(self.config,
                               self.rec_basename,
                               self.rec_basepath,
                               self.pages,
                               self.rec_timing_markers,
                               self.rec_timing_file,
                               self.get_record_animated_slides(),
                               self.get_record_second_region(),
                               self.get_record_webcam(),
                               audio_offset, webcam_offset, screencast_offset,
                               self.rec_stdout)
    Producer.produce_recording(self.root)
    
  def update_preview_img(self):
    imprev = self.list_preview_images[self.counter + 1]
    if self.counter > 0:
      self.cv2.delete("all")
    self.cv2.create_image(self.cv2.winfo_width()/2, self.cv2.winfo_height()/2, anchor = tk.CENTER, image = imprev)
    
  def next_block_special(self):
    self.slide_viewer.update_main_img()
    self.update_preview_img()

  def previous_block_special(self):
    self.slide_viewer.update_main_img()
    self.update_preview_img()


class ScreencasterView(BaseRecorder):

  def __init__(self, parent, project_name, *args, **kwargs):
    super().__init__(parent, project_name)
    
    self.additional_source_animated_slides_check['state'] = 'disabled'
    self.btn_keep_aspect_ratio_check['state'] = 'disabled'
    self.btn_fs['state'] = 'disabled'
    self.btn_rs_text.set("Resize Window to Geometry")
    
    self.root.after(500, self.load_and_init)
  
  def call_producer(self, audio_offset, webcam_offset, screencast_offset):
    Producer = MediaProducer(self.config,
                               self.rec_basename,
                               self.rec_basepath,
                               [],
                               self.rec_timing_markers,
                               self.rec_timing_file,
                               False,
                               self.get_record_second_region(),
                               self.get_record_webcam(),
                               audio_offset, webcam_offset, screencast_offset,
                               self.rec_stdout)
    Producer.produce_screencast(self.root)
    
  def resize_to_input(self):
    if self.get_valid_geometry():
      other_geom = self.new_geometry_entry.get()
      other_geom = other_geom.partition('x')
      result = subprocess.check_output(['xwininfo'], universal_newlines=True)
      _id = _x = _y = None
      for line in result.split('\n'):
        if line.startswith('xwininfo') and 'id:' in line:
          line = line.split('id:',1)
          _id = (line[1].split('"',1)[0]).strip()
        else:
          line = line.split(':',1)
          if 'Absolute upper-left X' in line[0]:
            _x=line[1].strip()
          elif 'Absolute upper-left Y' in line[0]:
            _y=line[1].strip()
      if _id:
        cmd = f"wmctrl -i -r {_id} -b remove,maximized_vert,maximized_horz"
        subprocess.Popen(cmd.split(' '), universal_newlines=True)
        cmd = f"wmctrl -i -r {_id} -e 0,{_x},{_y},{other_geom[0]},{other_geom[2]}"
        subprocess.Popen(cmd.split(' '), universal_newlines=True)
      self.second_offset_entry.delete(0,tk.END)
      self.second_offset_entry.insert(0,f"{other_geom[0]}x{other_geom[2]}+{_x}+{_y}")
      self.additional_source_another_region.set(True)
    

def main(project_name, startslide=1):
  root = tk.Tk() 
  if (Path(project_name).is_file() and project_name.endswith('.pdf')) or Path(project_name+'.pdf').is_file():
    MyApp = PresenterView(root, project_name, startslide)
  else:
    MyApp = ScreencasterView(root, project_name)
  tk.mainloop()


if __name__=='__main__':
  import plac
  plac.call(main)
