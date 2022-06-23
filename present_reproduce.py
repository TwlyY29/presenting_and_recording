import subprocess, re, os, signal, math
from datetime import datetime, timedelta
from pdf2image import convert_from_path
from PIL import Image,ImageTk,ImageDraw
from tempfile import TemporaryDirectory,NamedTemporaryFile
from pathlib import Path
import configparser

from present import MediaProducer, DEFAULT_CONFIG_FILE
import tkinter as tk
from tkinter import simpledialog

import sys

fmt = '%H:%M:%S.%f'

class bullshit():
  
  def __init__(self, project_name, is_screencast_or_presentation, max_h):
    self.rec_timing_markers = []
    self.rec_producer = None
    self.rec_basename = project_name.replace('.pdf','')
    self.rec_basepath = Path(os.getcwd()).absolute()
    self.rec_config_file = self.rec_basename + '.config'
    self.rec_timing_file = self.rec_basename + '-timing.chap'
    self.load_timings(self.rec_timing_file)
    # ~ print(self.rec_timing_markers)
    self.rec_stdout_file = self.rec_basename+'-ffmpeg.log'
    self.load_timing_offsets()
    # ~ print(self.rec_audio_offset)
    
    animated_slides = Path(self.rec_basename + '-screen.mkv').exists()
    second_region = Path(self.rec_basename + '-screencast.mkv').exists()
    webcam = Path(self.rec_basename+'-webcam.mkv').exists()
    
    try:
      tmp = tk.Tk()
    except tk.TclError:
      tmp = None
    
    config = configparser.ConfigParser()
    default_file = Path(DEFAULT_CONFIG_FILE).expanduser()
    if default_file.exists():
      config.read(default_file.resolve())
    specific_file = Path(self.rec_config_file).expanduser()
    if Path(specific_file).exists():
      print(f"read presentation-specific config from '{specific_file}'")
      config.read(specific_file.resolve())

    self.config = config['DEFAULT']
    
    if is_screencast_or_presentation == 'presentation':
      self.pages = convert_from_path(project_name,size=(None, max_h),dpi=self.config.getint("SlideLoadDpi", 300))
    elif is_screencast_or_presentation == 'screencast':
      self.pages = []
    else:
      self.pages = []
    
    with open(self.rec_stdout_file, 'a') as logfile:
      print("------------------------- REPRODUCE RUN -------------------------", file=logfile)
      Producer = MediaProducer(self.config,
                               self.rec_basename, 
                               self.rec_basepath, 
                               self.pages, 
                               self.rec_timing_markers, 
                               self.rec_timing_file,
                               animated_slides,
                               second_region,
                               webcam,
                               self.rec_audio_offset, self.rec_webcam_offset, self.rec_screencast_offset, 
                               rec_stdout = logfile)
      if is_screencast_or_presentation == 'presentation':
        Producer.produce_recording(tmp)
      elif is_screencast_or_presentation == 'screencast':
        Producer.produce_screencast(tmp)
      
  
  def load_timings(self, tf):
    with open(tf,'r') as _tf:
      start = _tf.readline()
      start = start.replace(' S','').strip()
      start = datetime.strptime(start, '%Y-%m-%d %H:%M:%S.%f')
      for line in _tf:
        t = line.split(' ')[0]
        dt = datetime.strptime(t, fmt)
        dt = timedelta(hours=dt.hour, minutes=dt.minute, seconds=dt.second, microseconds=dt.microsecond)
        self.rec_timing_markers.append((start+dt) - start)
  
  def load_timing_offsets(self):
    self.rec_audio_offset = '00:00:00.0'
    self.rec_webcam_offset = '00:00:00.0'
    self.rec_screencast_offset = '00:00:00.0'
    with open(self.rec_stdout_file, 'r') as logfile:
      for line in logfile:
        if line.startswith('audiooffset='):
          line = line.partition('=')
          self.rec_audio_offset = line[2].strip()
        elif line.startswith('webcamoffset='):
          line = line.partition('=')
          self.rec_webcam_offset = line[2].strip()
        elif line.startswith('screencastoffset='):
          line = line.partition('=')
          self.rec_screencast_offset = line[2].strip()

def main(project, wait=False, max_h=2160):
  what = ''
  if project.endswith('.pdf') or Path(project + '.pdf').is_file():
    what = 'presentation'
  else:
    what = 'screencast'
  bs = bullshit(project, what, max_h)
  if wait:
    reply = input("Press Enter to kill\n")
    print("thanks")
  print("bye")

if __name__=='__main__':
  import plac
  plac.call(main)
