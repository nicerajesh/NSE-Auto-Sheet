from __future__ import annotations
import os,sys,math,time,datetime as dt
from pathlib import Path
import pandas as pd,numpy as np,requests
from indicator import add_indicators_all
from strategy import scan_all
from backtest import run_backtest
from quality_gate import evaluate
from config import STRAT,BT
from d1_database import sync_latest
# NOTE: this replacement is intentionally limited to the final reporting section in the live file.
