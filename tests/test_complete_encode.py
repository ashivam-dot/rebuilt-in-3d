"""Run the real compositor/encoder on a small plate, without loading a depth model."""
import json
import math
import subprocess

import numpy as np
import soundfile as sf
from PIL import Image

from studio import compose
from studio.spec import Beat, Short


def test_a_fractional_duration_keeps_every_closing_frame_and_the_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, 'W', 180)
    monkeypatch.setattr(compose, 'H', 320)
    monkeypatch.setattr(compose.depth, 'estimate', lambda image, cache: np.full(
        (image.height, image.width), .5, dtype=np.float32))
    picture=tmp_path/'photo.jpg'
    Image.new('RGB',(180,320),(75,110,145)).save(picture)
    photo={'path':str(picture),'credit':'Photo: public domain','host':'Wikimedia Commons',
           'license':'Public domain','page':'https://commons.wikimedia.org/wiki/File:Test.jpg'}
    short=Short(id='encode-regression',kind='death',title='Test',beats=[Beat('Test ending.','photo:0')],
                facts=[],sources=[],loss=False,scene={'mood':'tribute','photos':[photo]})
    spoken=2.011
    wave=np.arange(round(spoken*24000))/24000
    sf.write(tmp_path/'narration.wav',.2*np.sin(2*np.pi*220*wave),24000)
    timing={'duration':spoken,'beats':[[0,spoken]],'words':[{'text':'Test','start':0,'end':.4,'beat':0}]}
    stats=compose.render(short,timing,tmp_path)
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-show_entries',
        'stream=codec_type,nb_read_frames,duration','-of','json',str(tmp_path/'short.mp4')]))
    video=next(s for s in probe['streams'] if s['codec_type']=='video')
    audio=next(s for s in probe['streams'] if s['codec_type']=='audio')
    assert int(video['nb_read_frames'])==stats['frames']==math.ceil((spoken+.6)*compose.FPS)
    assert float(audio['duration'])>=spoken
